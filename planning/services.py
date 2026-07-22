"""Helpers métier pour le planning musiciens."""

from __future__ import annotations

import logging
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    ParticipationStatus,
    SubstituteRequest,
)
from users.notify import notify_users

logger = logging.getLogger(__name__)

User = get_user_model()


STATUS_CODES = {
    "invited": {"label": "Invité", "color_token": "warning", "sort_order": 10},
    "confirmed": {"label": "Confirmé", "color_token": "success", "sort_order": 20},
    "maybe": {"label": "Peut-être", "color_token": "warning", "sort_order": 25},
    "declined": {"label": "Refusé", "color_token": "danger", "sort_order": 30},
    "replacement_needed": {
        "label": "Remplacement demandé",
        "color_token": "neutral",
        "sort_order": 40,
    },
}

RESPOND_MAP = {
    "yes": "confirmed",
    "no": "declined",
    "maybe": "maybe",
}


_STATUS_CACHE: dict[str, ParticipationStatus] | None = None


def ensure_participation_statuses(*, force: bool = False) -> dict[str, ParticipationStatus]:
    global _STATUS_CACHE
    if _STATUS_CACHE is not None and not force:
        return _STATUS_CACHE

    existing = {
        s.code: s
        for s in ParticipationStatus.objects.filter(code__in=STATUS_CODES.keys())
    }
    if len(existing) == len(STATUS_CODES) and not force:
        # Refresh labels/order if outdated without write on every call.
        stale = False
        for code, payload in STATUS_CODES.items():
            s = existing[code]
            if (
                s.label != payload["label"]
                or s.color_token != payload["color_token"]
                or s.sort_order != payload["sort_order"]
                or not s.is_active
            ):
                stale = True
                break
        if not stale:
            _STATUS_CACHE = existing
            return existing

    result: dict[str, ParticipationStatus] = {}
    for code, payload in STATUS_CODES.items():
        status, _ = ParticipationStatus.objects.update_or_create(
            code=code,
            defaults={
                "label": payload["label"],
                "color_token": payload["color_token"],
                "sort_order": payload["sort_order"],
                "is_active": True,
            },
        )
        result[code] = status
    _STATUS_CACHE = result
    return result


def get_status(code: str) -> ParticipationStatus:
    statuses = ensure_participation_statuses()
    return statuses[code]


def get_or_create_profile(user) -> MusicianProfile:
    profile, _ = MusicianProfile.objects.get_or_create(user=user)
    return profile


def set_participation_response(
    participation: EventParticipation,
    response: str,
    *,
    comment: str = "",
) -> EventParticipation:
    if response not in RESPOND_MAP:
        raise ValueError("Réponse invalide")
    old_code = participation.status.code if participation.status_id else None
    new_code = RESPOND_MAP[response]
    comment = (comment or "").strip()
    # Confirmé → Non (invalidation) ok ; Confirmé → Peut-être interdit.
    if old_code == "confirmed" and new_code == "maybe":
        raise ValueError(
            "Une présence confirmée ne peut pas passer en « peut-être »."
        )
    leaving_confirmed = old_code == "confirmed" and new_code == "declined"
    participation.status = get_status(new_code)
    if comment:
        participation.comment = comment
    participation.save(update_fields=["status", "comment", "updated_at"])
    if leaving_confirmed:
        notify_staff_presence_invalidated(
            participation, old_code=old_code, new_code=new_code
        )
    return participation


def notify_staff_presence_invalidated(
    participation: EventParticipation,
    *,
    old_code: str,
    new_code: str,
) -> int:
    """Alerte immédiate staff quand une présence confirmée est annulée / assouplie."""
    event = participation.event
    musician = participation.user
    name = musician.get_full_name() or musician.username
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    status_label = {
        "declined": "ne pourra pas venir",
        "replacement_needed": "demande un remplacement",
    }.get(new_code, f"passe de {old_code} à {new_code}")
    poste = participation.poste_label
    poste_bit = f" ({poste})" if poste and poste != "—" else ""
    motif = (participation.comment or "").strip()
    body_bits = [
        f"{name}{poste_bit} {status_label} pour « {event.titre} » ({date_label}).",
    ]
    if motif:
        body_bits.append(f"Motif : {motif[:200]}")
    if getattr(event, "statut", None) == Event.Statut.CONFIRME:
        body_bits.append("Événement déjà confirmé.")
    try:
        if getattr(event, "is_rehearsal", False):
            url = reverse("repetitions:detail", kwargs={"pk": event.pk})
        else:
            url = reverse("planning:event_roster", kwargs={"pk": event.pk})
    except Exception:
        url = "/planning/moi/"
    staff = User.objects.filter(is_active=True, is_staff=True)
    try:
        return notify_users(
            staff,
            title="JOY — Présence annulée",
            body=" ".join(body_bits),
            url=url,
        )
    except Exception:
        logger.exception(
            "Échec notif staff présence invalidée participation_id=%s",
            participation.pk,
        )
        return 0


def titulaires_queryset():
    """Musiciens actifs ayant un poste titulaire renseigné."""
    return User.objects.filter(
        is_musician=True,
        is_active=True,
        musician_profile__poste_titulaire__gt="",
    ).select_related("musician_profile")


def resolve_invite_slot(musician, poste: str) -> tuple[str, str]:
    """
    Valide le poste convoqué pour un musicien.

    Retourne (poste, role_kind). Lève ValueError si incohérent.
    Sans poste explicite : poste titulaire s’il existe, sinon l’unique slot.
    """
    poste = (poste or "").strip()
    try:
        profile = musician.musician_profile
    except MusicianProfile.DoesNotExist as exc:
        raise ValueError("Profil musicien manquant") from exc

    slots = invite_slots_for_profile(profile)
    if not slots:
        if not poste:
            return "", ""
        raise ValueError("Ce musicien n’a aucun poste renseigné")

    if not poste:
        # Défaut : titulaire, sinon unique chaise de remplacement.
        if profile.poste_titulaire:
            return (
                profile.poste_titulaire,
                EventParticipation.RoleKind.TITULAIRE,
            )
        if len(slots) == 1:
            return slots[0]["poste"], slots[0]["role_kind"]
        raise ValueError("Choisissez le poste pour lequel convoquer ce musicien")

    for slot in slots:
        if slot["poste"] == poste:
            return slot["poste"], slot["role_kind"]

    raise ValueError("Poste non associé à ce musicien")


def invite_slots_for_profile(profile: MusicianProfile) -> list[dict]:
    """Slots d’invitation (titulaire d’abord, puis remplaçants)."""
    slots: list[dict] = []
    if profile.poste_titulaire:
        slots.append(
            {
                "poste": profile.poste_titulaire,
                "role_kind": EventParticipation.RoleKind.TITULAIRE,
                "label": f"{profile.get_poste_titulaire_display()} (tit.)",
                "is_default": True,
            }
        )
    for poste in profile.postes_remplacant:
        slots.append(
            {
                "poste": poste,
                "role_kind": EventParticipation.RoleKind.REMPLACANT,
                "label": f"{profile.get_poste_remplacant_label(poste)} (remp.)",
                "is_default": False,
            }
        )
    if slots and not any(s["is_default"] for s in slots):
        slots[0]["is_default"] = True
    return slots


def invite_choices_for_musicians(musicians) -> list[dict]:
    """
    Options d’invitation aplaties : une entrée par (musicien, poste).

    value = « {user_id}:{poste} » pour le select HTML.
    Conservé pour compat ; préférer invite_musicians_for_form.
    """
    choices: list[dict] = []
    for entry in invite_musicians_for_form(musicians):
        if not entry["slots"]:
            choices.append(
                {
                    "value": f"{entry['user_id']}:",
                    "user_id": entry["user_id"],
                    "poste": "",
                    "label": entry["name"],
                }
            )
            continue
        for slot in entry["slots"]:
            choices.append(
                {
                    "value": f"{entry['user_id']}:{slot['poste']}",
                    "user_id": entry["user_id"],
                    "poste": slot["poste"],
                    "label": f"{entry['name']} · {slot['label']}",
                }
            )
    return choices


def invite_musicians_for_form(musicians) -> list[dict]:
    """
    Musiciens pour le formulaire d’invitation (titulaire par défaut).

    Chaque entrée : user_id, name, default_poste, slots[].
    """
    entries: list[dict] = []
    for m in musicians:
        name = m.get_full_name() or m.username
        try:
            profile = m.musician_profile
        except MusicianProfile.DoesNotExist:
            entries.append(
                {
                    "user_id": m.pk,
                    "name": name,
                    "default_poste": "",
                    "slots": [],
                }
            )
            continue
        slots = invite_slots_for_profile(profile)
        default = next((s["poste"] for s in slots if s.get("is_default")), "")
        if not default and slots:
            default = slots[0]["poste"]
        entries.append(
            {
                "user_id": m.pk,
                "name": name,
                "default_poste": default,
                "slots": [
                    {
                        "poste": s["poste"],
                        "label": s["label"],
                        "role_kind": s["role_kind"],
                        "is_default": bool(s.get("is_default")),
                    }
                    for s in slots
                ],
            }
        )
    return entries


def parse_invite_choice(raw: str) -> tuple[int | None, str]:
    """Parse « user_id:poste » depuis le formulaire d’invitation."""
    raw = (raw or "").strip()
    if not raw:
        return None, ""
    if ":" not in raw:
        try:
            return int(raw), ""
        except ValueError:
            return None, ""
    user_part, poste = raw.split(":", 1)
    try:
        return int(user_part), poste.strip()
    except ValueError:
        return None, ""


def invite_titulaires_to_event(event, *, send_notification: bool = False) -> int:
    """Convoque tous les titulaires à une date (ignore les déjà inscrits)."""
    invited = get_status("invited")
    musicians = list(titulaires_queryset())
    existing = set(
        EventParticipation.objects.filter(event=event).values_list(
            "user_id", flat=True
        )
    )
    to_create = []
    for u in musicians:
        if u.pk in existing:
            continue
        poste = u.musician_profile.poste_titulaire
        to_create.append(
            EventParticipation(
                event=event,
                user=u,
                status=invited,
                poste=poste,
                role_kind=EventParticipation.RoleKind.TITULAIRE,
            )
        )
    if to_create:
        EventParticipation.objects.bulk_create(to_create, ignore_conflicts=True)
        # bulk_create ne déclenche pas post_save → sync chat manuelle
        from chat.services import sync_participation_to_chat

        created_parts = list(
            EventParticipation.objects.filter(
                event=event, user_id__in=[p.user_id for p in to_create]
            ).select_related("user")
        )
        for part in created_parts:
            sync_participation_to_chat(part)
        if send_notification:
            notify_event_invite(event, [p.user for p in created_parts])
    return len(to_create)


def notify_event_invite(event, users) -> int:
    """Notification d’invitation au salon / événement."""
    users = list(users)
    if not users:
        return 0
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    body = (
        f"Invitation : « {event.titre} » ({date_label}). "
        f"Ouvrez le salon de discussion pour répondre."
    )
    return notify_users(
        users,
        title="JOY — Invitation",
        body=body,
        url="/chat/",
    )


def send_event_photos_requests(events, members) -> int:
    """
    Demande photos/vidéos aux membres pour chaque événement (J+7).

    Marque ``photos_request_sent_at`` même si 0 notif (évite de spammer au prochain run).
    Retourne le total de notifications envoyées.
    """
    from core.media_events import media_submit_url_for_event

    events = list(events)
    members = list(members)
    if not events:
        return 0

    total = 0
    now = timezone.now()
    for event in events:
        day = timezone.localtime(event.date_debut)
        title = f"Photos — {event.titre}"
        body = (
            f"Une semaine après « {event.titre} » "
            f"({day.strftime('%d/%m/%Y')}), "
            f"partagez vos photos et vidéos du jour !"
        )
        url = media_submit_url_for_event(event)
        if members:
            total += notify_users(members, title=title, body=body, url=url)
        Event.objects.filter(pk=event.pk).update(photos_request_sent_at=now)
        event.photos_request_sent_at = now
    return total


@transaction.atomic
def invite_musician_to_event(
    event,
    musician,
    *,
    poste: str = "",
    send_notification: bool = True,
) -> tuple[EventParticipation, bool]:
    """
    Invite un musicien individuellement (roster + salon) + notification optionnelle.

    ``poste`` est obligatoire si le musicien a plusieurs postes.
    Retourne (participation, created).
    """
    if not getattr(musician, "is_musician", False) or not musician.is_active:
        raise ValueError("Utilisateur non musicien ou inactif")
    poste, role_kind = resolve_invite_slot(musician, poste)
    invited = get_status("invited")
    try:
        part, created = EventParticipation.objects.get_or_create(
            event=event,
            user=musician,
            defaults={
                "status": invited,
                "poste": poste,
                "role_kind": role_kind,
            },
        )
    except IntegrityError:
        part = EventParticipation.objects.select_related("status").get(
            event=event, user=musician
        )
        created = False

    reinvite = False
    if not created:
        updates = ["updated_at"]
        if part.status_id != invited.pk:
            part.status = invited
            updates.append("status")
            reinvite = True
        if poste and part.poste != poste:
            part.poste = poste
            updates.append("poste")
            reinvite = True
        if part.role_kind != role_kind:
            part.role_kind = role_kind
            updates.append("role_kind")
            reinvite = True
        if reinvite or "poste" in updates or "role_kind" in updates:
            part.save(update_fields=updates)

    from chat.services import sync_participation_to_chat

    sync_participation_to_chat(part)
    if (created or reinvite) and send_notification:
        notify_event_invite(event, [musician])
    return part, created


@transaction.atomic
def propose_event(
    *,
    proposer,
    titre: str,
    event_type,
    venue,
    date_debut,
    date_fin=None,
    description: str = "",
    organisme: str = "",
    parent=None,
    public: bool = False,
    contact_nom: str = "",
    contact_telephone: str = "",
    contact_email: str = "",
):
    """
    Proposition d’événement par un musicien / adhérent / staff.

    Crée l’Event (tentative), un sondage brouillon lié, et laisse le signal
    chat créer un salon staff-only (pas de convocation auto des titulaires).
    """
    from events.models import Event

    titre = (titre or "").strip()
    if not titre:
        raise ValueError("Titre requis")

    event = Event(
        titre=titre,
        type=event_type,
        venue=venue,
        date_debut=date_debut,
        date_fin=date_fin,
        description=(description or "").strip(),
        statut=Event.Statut.TENTATIVE,
        public=public,
        parent=parent,
        organisme=(organisme or "").strip(),
        contact_nom=(contact_nom or "").strip(),
        contact_telephone=(contact_telephone or "").strip(),
        contact_email=(contact_email or "").strip(),
        proposed_by=proposer,
    )
    # Pas de convocation auto : le staff invite individuellement.
    event._skip_titulaire_invite = True
    event.save()

    proposal = DateProposal.objects.create(
        title=titre,
        description=(description or "").strip(),
        status=DateProposal.Status.DRAFT,
        created_by=proposer,
        linked_event=event,
    )
    DateOption.objects.create(
        proposal=proposal,
        starts_at=date_debut,
        ends_at=date_fin,
        label="",
        sort_order=0,
    )
    return event, proposal


@transaction.atomic
def launch_availability_poll(proposal: DateProposal, *, launched_by) -> DateProposal:
    """
    Autorise / lance le sondage : statut OPEN, message mis en évidence dans
    le salon, alerte (push ou e-mail) aux musiciens déjà invités au salon.
    """
    if proposal.status == DateProposal.Status.OPEN and proposal.launched_at:
        raise ValueError("Sondage déjà lancé")
    if proposal.status not in (
        DateProposal.Status.DRAFT,
        DateProposal.Status.OPEN,
    ):
        raise ValueError("Sondage non lançable")
    if not proposal.options.exists():
        raise ValueError("Ajoutez au moins une option de date")

    proposal.status = DateProposal.Status.OPEN
    proposal.launched_at = timezone.now()
    proposal.launched_by = launched_by
    proposal.save(
        update_fields=["status", "launched_at", "launched_by", "updated_at"]
    )

    event = proposal.linked_event
    poll_path = reverse("planning:poll_detail", kwargs={"pk": proposal.pk})

    if event is not None:
        from chat.models import ChatMembership, ChatMessage
        from chat.services import ensure_event_room, post_message

        room = ensure_event_room(event)
        local = timezone.localtime(event.date_debut)
        body = (
            f"Sondage de disponibilité lancé pour « {proposal.title} » "
            f"({local.strftime('%d/%m/%Y %H:%M')}).\n"
            f"Répondez au sondage : {poll_path}"
        )
        post_message(
            room=room,
            author=launched_by,
            body=body,
            kind=ChatMessage.Kind.POLL_LAUNCH,
            related_proposal=proposal,
        )

        member_ids = ChatMembership.objects.filter(
            room=room,
            left_at__isnull=True,
            user__is_musician=True,
            user__is_active=True,
        ).values_list("user_id", flat=True)
        recipients = list(User.objects.filter(pk__in=member_ids))
        part_users = list(
            User.objects.filter(
                event_participations__event=event,
                is_musician=True,
                is_active=True,
            ).distinct()
        )
        by_id = {u.pk: u for u in recipients + part_users}
        if launched_by:
            by_id.pop(launched_by.pk, None)
        notify_users(
            by_id.values(),
            title="JOY — Sondage disponibilité",
            body=(
                f"Sondage dispo : « {proposal.title} ». "
                f"Répondez dans le planning / salon."
            ),
            url=poll_path,
        )

    return proposal


def _remplacant_any_q() -> Q:
    """Profil avec au moins un poste remplaçant renseigné."""
    q = Q()
    for field in MusicianProfile.POSTE_REMPLACANT_FIELDS:
        q |= Q(**{f"{field}__gt": ""})
    return q


def _remplacant_matches_poste_q(poste: str) -> Q:
    q = Q()
    for field in MusicianProfile.POSTE_REMPLACANT_FIELDS:
        q |= Q(**{field: poste})
    return q


def _remplacant_in_postes_q(postes: list[str]) -> Q:
    q = Q()
    for field in MusicianProfile.POSTE_REMPLACANT_FIELDS:
        q |= Q(**{f"{field}__in": postes})
    return q


def eligible_substitutes_for(participation: EventParticipation):
    """Remplaçants du même poste / pupitre non déjà inscrits confirmés / invités."""
    section = participation.section_for_roster()

    qs = MusicianProfile.objects.select_related("user", "section").filter(
        user__is_active=True,
        user__is_musician=True,
    ).filter(_remplacant_any_q()).exclude(user_id=participation.user_id)

    if participation.poste:
        # Priorité : mêmes chaises en remplaçant, sinon même pupitre.
        same_poste = qs.filter(_remplacant_matches_poste_q(participation.poste))
        if same_poste.exists():
            qs = same_poste
        elif section is not None:
            section_postes = [
                code
                for code, section_code in MusicianProfile.POSTE_SECTION_CODE.items()
                if section_code == section.code
            ]
            qs = qs.filter(_remplacant_in_postes_q(section_postes))
    elif section is not None:
        qs = qs.filter(section=section)

    taken_ids = set(
        EventParticipation.objects.filter(
            event=participation.event,
            status__code__in=["confirmed", "invited", "maybe"],
        ).values_list("user_id", flat=True)
    )
    return [p for p in qs.distinct() if p.user_id not in taken_ids]


@transaction.atomic
def propose_substitute(
    participation: EventParticipation,
    candidate,
    *,
    note: str = "",
) -> SubstituteRequest:
    if candidate.pk == participation.user_id:
        raise ValueError("Impossible de se proposer soi-même")
    participation.status = get_status("replacement_needed")
    participation.save(update_fields=["status", "updated_at"])
    req, _ = SubstituteRequest.objects.update_or_create(
        participation=participation,
        candidate=candidate,
        defaults={
            "status": SubstituteRequest.Status.PROPOSED,
            "note": note,
        },
    )
    return req


@transaction.atomic
def respond_substitute_request(
    request_obj: SubstituteRequest,
    *,
    accept: bool,
) -> SubstituteRequest:
    request_obj = (
        SubstituteRequest.objects.select_for_update()
        .select_related("participation", "participation__event", "candidate")
        .get(pk=request_obj.pk)
    )
    if request_obj.status != SubstituteRequest.Status.PROPOSED:
        raise ValueError("Demande déjà traitée")

    if accept:
        orig = (
            EventParticipation.objects.select_for_update()
            .select_related("status")
            .get(pk=request_obj.participation_id)
        )
        # Another substitute may already have been accepted for this seat.
        if orig.status.code == "declined" and EventParticipation.objects.filter(
            event_id=orig.event_id,
            role_kind=EventParticipation.RoleKind.REMPLACANT,
            status__code="confirmed",
            comment="Remplaçant",
        ).exclude(user_id=request_obj.candidate_id).exists():
            raise ValueError("Un remplaçant a déjà accepté pour ce poste")

        request_obj.status = SubstituteRequest.Status.ACCEPTED
        request_obj.save(update_fields=["status", "updated_at"])
        confirmed = get_status("confirmed")
        declined = get_status("declined")
        EventParticipation.objects.update_or_create(
            event=orig.event,
            user=request_obj.candidate,
            defaults={
                "status": confirmed,
                "comment": "Remplaçant",
                "poste": orig.poste,
                "role_kind": EventParticipation.RoleKind.REMPLACANT,
            },
        )
        orig.status = declined
        orig.save(update_fields=["status", "updated_at"])
        SubstituteRequest.objects.filter(
            participation=orig,
            status=SubstituteRequest.Status.PROPOSED,
        ).exclude(pk=request_obj.pk).update(
            status=SubstituteRequest.Status.CANCELLED
        )
    else:
        request_obj.status = SubstituteRequest.Status.DECLINED
        request_obj.save(update_fields=["status", "updated_at"])
    return request_obj


@transaction.atomic
def lock_date_proposal(
    proposal: DateProposal,
    option: DateOption,
    *,
    event,
) -> DateProposal:
    if option.proposal_id != proposal.pk:
        raise ValueError("Option hors sondage")
    proposal.locked_option = option
    proposal.linked_event = event
    proposal.status = DateProposal.Status.LOCKED
    proposal.save(
        update_fields=["locked_option", "linked_event", "status", "updated_at"]
    )
    return proposal


def vote_counts_for_option(option: DateOption) -> dict[str, int]:
    counts = {"yes": 0, "no": 0, "maybe": 0}
    # Prefer prefetched cache when available (avoids N+1 on poll detail).
    votes = option.votes.all()
    if hasattr(votes, "_result_cache") and votes._result_cache is not None:
        for vote in votes:
            if vote.choice in counts:
                counts[vote.choice] += 1
        return counts
    for choice in votes.values_list("choice", flat=True):
        if choice in counts:
            counts[choice] += 1
    return counts


def user_can_access_poll(user, proposal: DateProposal) -> bool:
    """Staff always; otherwise must be invited / participant on the linked event."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    event = proposal.linked_event
    if event is None:
        return False
    return EventParticipation.objects.filter(event=event, user=user).exists()


def cast_date_vote(option: DateOption, user, choice: str) -> DateVote:
    if choice not in DateVote.Choice.values:
        raise ValueError("Vote invalide")
    proposal = option.proposal
    if not proposal.is_open:
        raise ValueError("Sondage fermé")
    if not user_can_access_poll(user, proposal):
        raise ValueError("Vous n’êtes pas concerné par ce sondage")
    vote, _ = DateVote.objects.update_or_create(
        option=option,
        user=user,
        defaults={"choice": choice},
    )
    return vote


def get_participation_for(event, user) -> EventParticipation | None:
    return (
        EventParticipation.objects.select_related("status")
        .filter(event=event, user=user)
        .first()
    )


def require_participation(event, user) -> EventParticipation:
    return get_object_or_404(
        EventParticipation.objects.select_related("status"),
        event=event,
        user=user,
    )


def _is_concert_type(event) -> bool:
    nom = (getattr(getattr(event, "type", None), "nom", None) or "").strip().lower()
    return "concert" in nom


def _is_rehearsal_type(event) -> bool:
    return bool(getattr(event, "is_rehearsal", False))


def _expected_sections() -> list[OrchestraSection]:
    """Pupitres actifs pour lesquels au moins un titulaire est en roster."""
    return list(
        OrchestraSection.objects.filter(
            is_active=True,
            musicians__poste_titulaire__gt="",
            musicians__user__is_active=True,
            musicians__user__is_musician=True,
        )
        .distinct()
        .order_by("sort_order", "name")
    )


def remplacants_by_section_code() -> dict[str, list[dict]]:
    """
    Remplaçants indexés par code de pupitre (via postes remplaçant).

    Chaque entrée : user_id, name, poste, invite_slot (« user_id:poste »).
    Un musicien n’apparaît qu’une fois par pupitre (1er poste remp. matching).
    """
    profiles = (
        MusicianProfile.objects.select_related("user")
        .filter(user__is_active=True, user__is_musician=True)
        .filter(_remplacant_any_q())
    )
    by_section: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set[int]] = defaultdict(set)
    for profile in profiles:
        name = profile.user.get_full_name() or profile.user.username
        for poste in profile.postes_remplacant:
            section_code = MusicianProfile.POSTE_SECTION_CODE.get(poste or "")
            if not section_code or profile.user_id in seen[section_code]:
                continue
            seen[section_code].add(profile.user_id)
            by_section[section_code].append(
                {
                    "user_id": profile.user_id,
                    "name": name,
                    "poste": poste,
                    "invite_slot": f"{profile.user_id}:{poste}",
                }
            )
    return by_section


def calendar_summaries_for_events(events) -> dict[int, dict]:
    """
    Résumés calendrier (présence + pupitres manquants), indexés par event.pk.

    Présents = participations confirmées, ventilées titulaire / remplaçant.
    Instruments manquants = pupitres attendus sans aucun confirmé.
    """
    events = list(events)
    if not events:
        return {}

    expected = _expected_sections()
    expected_ids = {s.pk for s in expected}
    remplacants_idx = remplacants_by_section_code()
    by_event_confirmed: dict[int, list] = defaultdict(list)
    by_event_taken: dict[int, set[int]] = defaultdict(set)

    parts = (
        EventParticipation.objects.filter(
            event_id__in=[e.pk for e in events],
            status__code__in=["confirmed", "invited", "maybe"],
        )
        .select_related("user__musician_profile__section", "status")
        .order_by("pk")
    )
    for p in parts:
        by_event_taken[p.event_id].add(p.user_id)
        if p.status.code == "confirmed":
            by_event_confirmed[p.event_id].append(p)

    summaries: dict[int, dict] = {}
    for event in events:
        confirmed = by_event_confirmed.get(event.pk, [])
        n_tit = 0
        n_rem = 0
        covered_section_ids: set[int] = set()
        for p in confirmed:
            try:
                profile = p.user.musician_profile
            except MusicianProfile.DoesNotExist:
                profile = None
            if p.role_kind == EventParticipation.RoleKind.REMPLACANT:
                n_rem += 1
            elif p.role_kind == EventParticipation.RoleKind.TITULAIRE:
                n_tit += 1
            elif (
                profile is not None
                and profile.is_remplacant
                and not profile.is_titulaire
            ):
                n_rem += 1
            else:
                n_tit += 1
            section = p.section_for_roster()
            if section is not None and section.pk in expected_ids:
                covered_section_ids.add(section.pk)

        missing_sections = [s for s in expected if s.pk not in covered_section_ids]
        missing = [s.name for s in missing_sections]
        taken = by_event_taken.get(event.pk, set())
        missing_detail = []
        for section in missing_sections:
            eligible = [
                entry
                for entry in remplacants_idx.get(section.code, [])
                if entry["user_id"] not in taken
            ]
            missing_detail.append(
                {
                    "section_id": section.pk,
                    "code": section.code,
                    "name": section.name,
                    "eligible": eligible,
                }
            )
        local_start = timezone.localtime(event.date_debut)
        venue = event.venue
        lieu = ""
        if venue is not None:
            lieu = f"{venue.nom} — {venue.ville}" if venue.ville else venue.nom

        is_concert = _is_concert_type(event)
        is_rehearsal = _is_rehearsal_type(event)
        statut = getattr(event, "statut", "") or ""
        is_proposal = (not is_rehearsal) and statut == Event.Statut.TENTATIVE
        is_confirmed = (not is_rehearsal) and statut == Event.Statut.CONFIRME
        if is_rehearsal:
            layer = "rehearsal"
            kind_label = "Répétition"
        elif is_proposal:
            layer = "proposal"
            kind_label = "Proposition"
        elif is_confirmed:
            layer = "confirmed"
            kind_label = "Confirmé"
        else:
            layer = "other"
            kind_label = getattr(getattr(event, "type", None), "nom", "") or "Événement"
        type_nom = getattr(getattr(event, "type", None), "nom", "") or ""
        summaries[event.pk] = {
            "titre": event.titre,
            "is_concert": is_concert,
            "is_rehearsal": is_rehearsal,
            "is_proposal": is_proposal,
            "is_confirmed": is_confirmed,
            "statut": statut,
            "layer": layer,
            "kind_label": kind_label,
            "type_nom": type_nom,
            "date_label": local_start.strftime("%d/%m/%Y"),
            "time_label": local_start.strftime("%H:%M"),
            "lieu": lieu,
            "n_titulaires": n_tit,
            "n_remplacants": n_rem,
            "n_presents": n_tit + n_rem,
            "instruments_manquants": missing,
            "instruments_manquants_label": (
                ", ".join(missing) if missing else "Aucun"
            ),
            "instruments_manquants_detail": missing_detail,
        }
    return summaries


def attach_calendar_summaries(events) -> list:
    """Attache ``event.cal_summary`` à chaque événement (mutates in place)."""
    summaries = calendar_summaries_for_events(events)
    for event in events:
        event.cal_summary = summaries.get(event.pk, {})
    return list(events)


def calendar_chat_links_for_user(events, user) -> dict[int, dict]:
    """
    Liens salon + non lus pour le calendrier / détail événement.

    - Membre actif → ``room_id`` + ``unread``
    - Staff sans membership → ``room_id`` + ``unread`` 0 si le salon existe
    Tolère l’absence des tables chat (migration pas encore appliquée).
    """
    events = list(events)
    if not events or user is None or not getattr(user, "is_authenticated", False):
        return {}

    event_ids = [e.pk for e in events]
    is_staff = bool(
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    )
    try:
        from django.db import OperationalError, ProgrammingError

        from chat.models import ChatMembership, ChatRoom
        from chat.services import unread_count

        memberships = list(
            ChatMembership.objects.filter(
                user=user,
                left_at__isnull=True,
                room__is_active=True,
                room__event_id__in=event_ids,
            ).select_related("room")
        )
    except (ProgrammingError, OperationalError, ImportError):
        return {}

    links: dict[int, dict] = {}
    for m in memberships:
        event_id = m.room.event_id
        if event_id is None:
            continue
        links[event_id] = {
            "room_id": m.room_id,
            "unread": unread_count(m),
        }

    if is_staff:
        missing_ids = [eid for eid in event_ids if eid not in links]
        if missing_ids:
            try:
                rooms = ChatRoom.objects.filter(
                    event_id__in=missing_ids, is_active=True
                ).only("pk", "event_id")
            except (ProgrammingError, OperationalError):
                rooms = []
            for room in rooms:
                links[room.event_id] = {"room_id": room.pk, "unread": 0}

    return links


def attach_calendar_chat_links(events, user) -> list:
    """Attache ``event.cal_chat`` (dict ou None) à chaque événement."""
    links = calendar_chat_links_for_user(events, user)
    for event in events:
        event.cal_chat = links.get(event.pk)
    return list(events)


def attach_calendar_setlists(events) -> list:
    """Attache ``event.cal_setlist`` ({id, title} ou None) pour la setlist active."""
    events = list(events)
    for event in events:
        event.cal_setlist = None
    if not events:
        return events
    try:
        from django.db import OperationalError, ProgrammingError

        from repertoire.models import Setlist
    except ImportError:
        return events

    event_ids = [e.pk for e in events]
    try:
        rows = (
            Setlist.objects.filter(event_id__in=event_ids, is_active=True)
            .order_by("event_id", "-updated_at")
            .values("id", "title", "event_id")
        )
    except (ProgrammingError, OperationalError):
        return events

    by_event: dict[int, dict] = {}
    for row in rows:
        eid = row["event_id"]
        if eid not in by_event:
            by_event[eid] = {"id": row["id"], "title": row["title"]}
    for event in events:
        event.cal_setlist = by_event.get(event.pk)
    return events


def chat_link_for_event(event, user) -> dict | None:
    """Salon + non lus pour un événement, ou None si pas d’accès."""
    return calendar_chat_links_for_user([event], user).get(event.pk)


def draft_proposal_for_event(event) -> DateProposal | None:
    """Sondage brouillon lié à l’événement (en attente de lancement staff)."""
    return (
        DateProposal.objects.filter(
            linked_event=event,
            status=DateProposal.Status.DRAFT,
        )
        .order_by("-created_at")
        .first()
    )
