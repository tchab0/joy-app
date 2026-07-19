"""Helpers métier pour le planning musiciens."""

from __future__ import annotations

import logging
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

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
from users.notify_sms import notify_users_sms

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


def ensure_participation_statuses() -> dict[str, ParticipationStatus]:
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
    participation.status = get_status(RESPOND_MAP[response])
    if comment:
        participation.comment = comment
    participation.save(update_fields=["status", "comment", "updated_at"])
    return participation


def titulaires_queryset():
    """Musiciens actifs ayant un poste titulaire renseigné."""
    return User.objects.filter(
        is_musician=True,
        is_active=True,
        musician_profile__poste_titulaire__gt="",
    )


def invite_titulaires_to_event(event, *, send_sms: bool = False) -> int:
    """Convoque tous les titulaires à une date (ignore les déjà inscrits)."""
    invited = get_status("invited")
    musicians = list(titulaires_queryset())
    existing = set(
        EventParticipation.objects.filter(event=event).values_list(
            "user_id", flat=True
        )
    )
    to_create = [
        EventParticipation(event=event, user=u, status=invited)
        for u in musicians
        if u.pk not in existing
    ]
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
        if send_sms:
            notify_event_invite_sms(event, [p.user for p in created_parts])
    return len(to_create)


def notify_event_invite_sms(event, users) -> int:
    """SMS instantané d’invitation au salon / événement."""
    users = list(users)
    if not users:
        return 0
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    body = (
        f"JOY — Invitation : « {event.titre} » ({date_label}). "
        f"Ouvrez le salon de discussion pour répondre."
    )
    return notify_users_sms(users, body)


@transaction.atomic
def invite_musician_to_event(
    event,
    musician,
    *,
    send_sms: bool = True,
) -> tuple[EventParticipation, bool]:
    """
    Invite un musicien individuellement (roster + salon) + SMS optionnel.

    Retourne (participation, created).
    """
    if not getattr(musician, "is_musician", False) or not musician.is_active:
        raise ValueError("Utilisateur non musicien ou inactif")
    invited = get_status("invited")
    part, created = EventParticipation.objects.get_or_create(
        event=event,
        user=musician,
        defaults={"status": invited},
    )
    from chat.services import sync_participation_to_chat

    sync_participation_to_chat(part)
    if created and send_sms:
        notify_event_invite_sms(event, [musician])
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
    le salon, SMS instantané aux musiciens déjà invités au salon.
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
        sms_body = (
            f"JOY — Sondage dispo : « {proposal.title} ». "
            f"Répondez dans l’app planning / salon."
        )
        notify_users_sms(by_id.values(), sms_body)

    return proposal


def eligible_substitutes_for(participation: EventParticipation):
    """Remplaçants du même pupitre non déjà inscrits confirmés / invités."""
    try:
        profile = participation.user.musician_profile
        section = profile.section
    except MusicianProfile.DoesNotExist:
        section = None

    qs = MusicianProfile.objects.select_related("user", "section").filter(
        user__is_active=True,
        user__is_musician=True,
        poste_remplacant__gt="",
    ).exclude(user_id=participation.user_id)

    if section is not None:
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
    if request_obj.status != SubstituteRequest.Status.PROPOSED:
        raise ValueError("Demande déjà traitée")

    if accept:
        request_obj.status = SubstituteRequest.Status.ACCEPTED
        request_obj.save(update_fields=["status", "updated_at"])
        confirmed = get_status("confirmed")
        declined = get_status("declined")
        EventParticipation.objects.update_or_create(
            event=request_obj.participation.event,
            user=request_obj.candidate,
            defaults={"status": confirmed, "comment": "Remplaçant"},
        )
        orig = request_obj.participation
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
    for choice in option.votes.values_list("choice", flat=True):
        if choice in counts:
            counts[choice] += 1
    return counts


def cast_date_vote(option: DateOption, user, choice: str) -> DateVote:
    if choice not in DateVote.Choice.values:
        raise ValueError("Vote invalide")
    proposal = option.proposal
    if not proposal.is_open:
        raise ValueError("Sondage fermé")
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
    by_event_confirmed: dict[int, list] = defaultdict(list)

    parts = (
        EventParticipation.objects.filter(
            event_id__in=[e.pk for e in events],
            status__code="confirmed",
        )
        .select_related("user__musician_profile__section")
        .order_by("pk")
    )
    for p in parts:
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
            if profile is not None and profile.is_remplacant and not profile.is_titulaire:
                n_rem += 1
            else:
                n_tit += 1
            if profile is not None and profile.section_id in expected_ids:
                covered_section_ids.add(profile.section_id)

        missing = [s.name for s in expected if s.pk not in covered_section_ids]
        local_start = timezone.localtime(event.date_debut)
        venue = event.venue
        lieu = ""
        if venue is not None:
            lieu = f"{venue.nom} — {venue.ville}" if venue.ville else venue.nom

        summaries[event.pk] = {
            "titre": event.titre,
            "is_concert": _is_concert_type(event),
            "type_nom": getattr(getattr(event, "type", None), "nom", "") or "",
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
