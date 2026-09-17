"""Helpers métier planning — module interne."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from events.models import Event
from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EquipmentItem,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    ParticipationStatus,
    SubstituteRequest,
)

logger = logging.getLogger(__name__)
User = get_user_model()

from planning.services._notify import notify_users
from planning.services.calendar_ops import (
    _deadline_label,
    _is_rehearsal_type,
    _user_display_label,
)
from planning.services.constants import RESPOND_MAP
from planning.services.invites import invite_titulaires_to_event, notify_event_invite, titulaires_queryset
from planning.services.rsvp import get_participation_for, set_participation_response

def poll_notification_recipients(proposal: DateProposal) -> list:
    """
    Musiciens concernés par un sondage :
    - audience « tous » → musiciens actifs
    - sinon membres du salon source (ou salon événement)
    - + participations événement lié (sans exclure le lanceur)
    """
    from chat.models import ChatMembership

    if proposal.audience == DateProposal.Audience.ALL:
        return list(
            User.objects.filter(is_musician=True, is_active=True).order_by("pk")
        )

    recipients: list = []
    room = proposal.source_room
    if room is None and proposal.linked_event_id:
        from chat.services import ensure_event_room

        room = ensure_event_room(proposal.linked_event)
    if room is not None:
        member_ids = ChatMembership.objects.filter(
            room=room,
            left_at__isnull=True,
            user__is_musician=True,
            user__is_active=True,
        ).values_list("user_id", flat=True)
        recipients = list(User.objects.filter(pk__in=member_ids))

    event = proposal.linked_event
    if event is not None:
        part_users = list(
            User.objects.filter(
                event_participations__event=event,
                is_musician=True,
                is_active=True,
            ).distinct()
        )
        recipients = recipients + part_users

    by_id = {u.pk: u for u in recipients}
    return list(by_id.values())


def _poll_notify_body(proposal: DateProposal, *, reminder: bool = False) -> str:
    deadline_bit = ""
    if proposal.deadline:
        prefix = " avant le " if reminder else " Répondez avant le "
        deadline_bit = f"{prefix}{proposal.deadline.strftime('%d/%m/%Y')}."
    kind_bit = (
        "chaque proposition"
        if proposal.is_text_poll
        else "chaque date proposée"
    )
    if reminder:
        return (
            f"Rappel — sondage « {proposal.title} » "
            f"en attente de votre réponse{deadline_bit} "
            f"Indiquez Oui / Peut-être / Non pour {kind_bit}."
        )
    return (
        f"Sondage « {proposal.title} ».{deadline_bit} "
        f"Indiquez Oui / Peut-être / Non pour {kind_bit}."
    )


def notify_availability_poll(proposal: DateProposal) -> int:
    """Envoie (ou renvoie) les notifications de sondage aux destinataires."""
    users = poll_notification_recipients(proposal)
    poll_path = reverse("planning:poll_detail", kwargs={"pk": proposal.pk})
    return notify_users(
        users,
        title="JOY — À répondre · Sondage",
        body=_poll_notify_body(proposal),
        url=poll_path,
        requires_response=True,
        related_type="proposal",
        related_id=proposal.pk,
        notify_type="proposal",
    )


def notify_poll_deadline_reminder(proposal: DateProposal) -> int:
    """Rappel J−7 : notifie les destinataires qui n’ont pas encore répondu."""
    users = [
        u
        for u in poll_notification_recipients(proposal)
        if not user_has_answered_poll(u, proposal)
    ]
    if not users:
        return 0
    poll_path = reverse("planning:poll_detail", kwargs={"pk": proposal.pk})
    try:
        return notify_users(
            users,
            title="JOY — À répondre · Rappel sondage",
            body=_poll_notify_body(proposal, reminder=True),
            url=poll_path,
            requires_response=True,
            related_type="proposal",
            related_id=proposal.pk,
            notify_type="proposal",
        )
    except Exception:
        logger.exception(
            "Échec rappel deadline proposal_id=%s", proposal.pk
        )
        return 0


def send_due_poll_deadline_reminders(
    *,
    as_of: date | None = None,
    dry_run: bool = False,
    days_before: int = 7,
) -> tuple[int, int]:
    """
    Relance les sondages OPEN dont la deadline tombe dans ``days_before`` jours.

    Retourne (nb sondages traités, nb notifications envoyées).
    Marque ``deadline_reminder_sent_at`` même si 0 destinataire (évite de
    retraiter au prochain run).
    """
    today = as_of or timezone.localdate()
    days = max(1, int(days_before or 7))
    target = today + timedelta(days=days)
    now = timezone.now()
    qs = (
        DateProposal.objects.filter(
            status=DateProposal.Status.OPEN,
            deadline=target,
            deadline_reminder_sent_at__isnull=True,
        )
        .prefetch_related(
            Prefetch(
                "options",
                queryset=DateOption.objects.order_by("sort_order", "starts_at").prefetch_related(
                    "votes"
                ),
            )
        )
        .select_related("linked_event")
        .order_by("deadline", "pk")
    )
    treated = 0
    sent = 0
    for proposal in qs:
        treated += 1
        if dry_run:
            continue
        sent += notify_poll_deadline_reminder(proposal)
        DateProposal.objects.filter(pk=proposal.pk).update(
            deadline_reminder_sent_at=now,
            updated_at=now,
        )
        proposal.deadline_reminder_sent_at = now
    return treated, sent


@transaction.atomic
def launch_availability_poll(proposal: DateProposal, *, launched_by) -> DateProposal:
    """
    Autorise / lance le sondage : statut OPEN, alerte (push ou e-mail)
    aux destinataires (salon / orchestre / roster).
    """
    if proposal.status == DateProposal.Status.OPEN and proposal.launched_at:
        raise ValueError("Sondage déjà lancé")
    if proposal.status not in (
        DateProposal.Status.DRAFT,
        DateProposal.Status.OPEN,
    ):
        raise ValueError("Sondage non lançable")
    if not proposal.options.exists():
        raise ValueError("Ajoutez au moins une option")

    proposal.status = DateProposal.Status.OPEN
    proposal.launched_at = timezone.now()
    proposal.launched_by = launched_by
    proposal.save(
        update_fields=["status", "launched_at", "launched_by", "updated_at"]
    )

    notify_availability_poll(proposal)

    return proposal


@transaction.atomic
def close_poll(proposal: DateProposal, *, locked_option: DateOption | None = None) -> DateProposal:
    """Clôture un sondage sans créer / confirmer d’événement (sondages salon / texte)."""
    if proposal.status != DateProposal.Status.OPEN:
        raise ValueError("Ce sondage n’est plus ouvert.")
    if locked_option is not None and locked_option.proposal_id != proposal.pk:
        raise ValueError("Option hors sondage")
    proposal.status = DateProposal.Status.LOCKED
    proposal.locked_option = locked_option
    proposal.save(update_fields=["status", "locked_option", "updated_at"])
    return proposal


def _parse_poll_dt(value: str | None):
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    dt = parse_datetime(raw.replace(" ", "T", 1) if "T" not in raw and " " in raw else raw)
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@transaction.atomic
def create_and_launch_chat_poll(
    *,
    room,
    author,
    title: str,
    description: str = "",
    option_kind: str = DateProposal.OptionKind.DATES,
    audience: str = DateProposal.Audience.ROOM,
    options: list[dict],
    deadline: date | None = None,
    thread_event_id=None,
):
    """
    Crée un sondage depuis un salon chat, le lance immédiatement,
    poste un message POLL_LAUNCH et notifie l’audience.

    Retourne ``(proposal, message)``.
    """
    from chat.models import ChatMessage
    from chat.services import post_message

    title = (title or "").strip()
    if not title:
        raise ValueError("Titre requis.")
    if option_kind not in DateProposal.OptionKind.values:
        raise ValueError("Type de sondage invalide.")
    if audience not in DateProposal.Audience.values:
        raise ValueError("Audience invalide.")
    if not options:
        raise ValueError("Ajoutez au moins une option.")

    linked_event = None
    if getattr(room, "event_id", None) and option_kind == DateProposal.OptionKind.DATES:
        linked_event = room.event

    proposal = DateProposal.objects.create(
        title=title,
        description=(description or "").strip(),
        created_by=author,
        status=DateProposal.Status.DRAFT,
        option_kind=option_kind,
        audience=audience,
        source_room=room,
        linked_event=linked_event,
        deadline=deadline,
    )

    created = 0
    for raw in options:
        if not isinstance(raw, dict):
            continue
        label = (raw.get("label") or "").strip()
        if option_kind == DateProposal.OptionKind.TEXT:
            if not label:
                continue
            DateOption.objects.create(
                proposal=proposal,
                starts_at=None,
                ends_at=None,
                label=label[:120],
                sort_order=created,
            )
            created += 1
            continue
        starts = _parse_poll_dt(raw.get("starts_at") or raw.get("starts"))
        if starts is None:
            continue
        ends = _parse_poll_dt(raw.get("ends_at") or raw.get("ends"))
        DateOption.objects.create(
            proposal=proposal,
            starts_at=starts,
            ends_at=ends,
            label=label[:120],
            sort_order=created,
        )
        created += 1

    if created == 0:
        proposal.delete()
        if option_kind == DateProposal.OptionKind.TEXT:
            raise ValueError("Ajoutez au moins une option texte.")
        raise ValueError("Ajoutez au moins une option de date.")

    launch_availability_poll(proposal, launched_by=author)

    body_lines = [f"📊 Sondage : {proposal.title}"]
    if proposal.description:
        body_lines.append(proposal.description)
    if proposal.deadline:
        body_lines.append(
            f"Répondre avant le {proposal.deadline.strftime('%d/%m/%Y')}."
        )
    message = post_message(
        room=room,
        author=author,
        body="\n".join(body_lines),
        kind=ChatMessage.Kind.POLL_LAUNCH,
        related_proposal=proposal,
        thread_event_id=thread_event_id,
        require_thread=False,
    )
    return proposal, message

def apply_locked_option_votes_to_participations(
    option: DateOption,
    event,
) -> int:
    """
    Après confirmation d’une date : reporte les votes de l’option retenue
    sur les participations existantes.

    - oui → confirmed (présent / dispo)
    - non → declined (absent)
    - peut-être → maybe

    Ne crée pas de participations. Les non-votants restent inchangés
    (souvent « invited ») et peuvent répondre ensuite sur l’événement.
    """
    votes = {
        vote.user_id: vote.choice
        for vote in DateVote.objects.filter(option=option)
        if vote.choice in RESPOND_MAP
    }
    if not votes:
        return 0

    updated = 0
    participations = EventParticipation.objects.filter(
        event=event,
        user_id__in=votes.keys(),
    ).select_related("status")
    for part in participations:
        choice = votes[part.user_id]
        target = RESPOND_MAP[choice]
        if part.status_id and part.status.code == target:
            continue
        try:
            set_participation_response(part, choice)
            updated += 1
        except ValueError:
            logger.warning(
                "Sync vote→participation ignorée event_id=%s user_id=%s choice=%s",
                getattr(event, "pk", None),
                part.user_id,
                choice,
                exc_info=True,
            )
    return updated


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
    apply_locked_option_votes_to_participations(option, event)
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


def format_poll_vote_counts(counts: dict[str, int] | None) -> str:
    """Libellé court visible par tous : Oui / Non / Peut-être."""
    c = counts or {}
    return (
        f"Oui {int(c.get('yes', 0))} · "
        f"Non {int(c.get('no', 0))} · "
        f"Peut-être {int(c.get('maybe', 0))}"
    )


def user_can_access_poll(user, proposal: DateProposal) -> bool:
    """Staff ; audience orchestre ; membres du salon source ; participants événement."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    if proposal.audience == DateProposal.Audience.ALL:
        return bool(getattr(user, "is_musician", False) and user.is_active)
    if proposal.source_room_id:
        from chat.models import ChatMembership

        if ChatMembership.objects.filter(
            room_id=proposal.source_room_id,
            user=user,
            left_at__isnull=True,
        ).exists():
            return True
    event = proposal.linked_event
    if event is None:
        return False
    return EventParticipation.objects.filter(event=event, user=user).exists()


def _polls_accessible_q_for_user(user) -> Q:
    """Filtre ORM approximatif des sondages accessibles (hors staff)."""
    from chat.models import ChatMembership

    room_ids = list(
        ChatMembership.objects.filter(
            user=user, left_at__isnull=True
        ).values_list("room_id", flat=True)
    )
    return (
        Q(audience=DateProposal.Audience.ALL)
        | Q(source_room_id__in=room_ids)
        | Q(linked_event__participations__user=user)
    )


def user_can_edit_poll_deadline(user, proposal: DateProposal) -> bool:
    """Auteur du sondage ou staff."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    return proposal.created_by_id == getattr(user, "pk", None)


def user_can_edit_poll_options(user, proposal: DateProposal) -> bool:
    """Mêmes droits que pour la deadline (auteur ou staff)."""
    return user_can_edit_poll_deadline(user, proposal)


def update_poll_options(
    proposal: DateProposal,
    *,
    updates: list[dict],
    new_options: list[dict] | None = None,
    delete_ids: list[int] | None = None,
) -> DateProposal:
    """
    Met à jour les options d’un sondage (dates ou texte).

    ``updates`` : [{id, starts_at?, ends_at?, label?}, ...]
    ``new_options`` : [{starts_at?, ends_at?, label?}, ...]
    ``delete_ids`` : pks à supprimer (votes en cascade).

    Refusé si le sondage est verrouillé / annulé.
    Conserve au moins une option. Si l’événement lié est encore
    ``tentative`` et qu’il ne reste qu’une option datée, synchronise
    ``date_debut`` / ``date_fin`` de l’événement.
    """
    from events.models import Event

    if proposal.status in (
        DateProposal.Status.LOCKED,
        DateProposal.Status.CANCELLED,
    ):
        raise ValueError("Ce sondage est clos — options non modifiables.")

    existing = {o.pk: o for o in proposal.options.all()}
    delete_ids = list(delete_ids or [])
    new_options = list(new_options or [])
    text_mode = proposal.is_text_poll

    remaining_ids = set(existing) - set(delete_ids)
    if not remaining_ids and not new_options:
        raise ValueError("Il faut au moins une option.")

    for raw in updates:
        opt_id = raw.get("id")
        if opt_id not in remaining_ids:
            continue
        opt = existing[opt_id]
        label = (raw.get("label") or "").strip()
        if text_mode:
            if not label:
                raise ValueError("Chaque option texte doit avoir un libellé.")
            opt.label = label[:120]
            opt.starts_at = None
            opt.ends_at = None
            opt.save(update_fields=["starts_at", "ends_at", "label"])
            continue
        starts = raw.get("starts_at")
        if starts is None:
            raise ValueError("Chaque option doit avoir une date/heure de début.")
        opt.starts_at = starts
        opt.ends_at = raw.get("ends_at")
        if "label" in raw:
            opt.label = label[:120]
        opt.save(update_fields=["starts_at", "ends_at", "label"])

    for opt_id in delete_ids:
        opt = existing.get(opt_id)
        if opt is not None:
            opt.delete()

    next_order = (
        proposal.options.order_by("-sort_order")
        .values_list("sort_order", flat=True)
        .first()
    )
    sort_order = (next_order + 1) if next_order is not None else 0
    for raw in new_options:
        label = (raw.get("label") or "").strip()
        if text_mode:
            if not label:
                continue
            DateOption.objects.create(
                proposal=proposal,
                starts_at=None,
                ends_at=None,
                label=label[:120],
                sort_order=sort_order,
            )
            sort_order += 1
            continue
        starts = raw.get("starts_at")
        if starts is None:
            continue
        DateOption.objects.create(
            proposal=proposal,
            starts_at=starts,
            ends_at=raw.get("ends_at"),
            label=label[:120],
            sort_order=sort_order,
        )
        sort_order += 1

    if not proposal.options.exists():
        raise ValueError("Il faut au moins une option.")

    event = proposal.linked_event
    options = list(proposal.options.order_by("sort_order", "starts_at"))
    if (
        event is not None
        and event.statut == Event.Statut.TENTATIVE
        and len(options) == 1
        and options[0].starts_at is not None
    ):
        only = options[0]
        event.date_debut = only.starts_at
        event.date_fin = only.ends_at
        event.save(update_fields=["date_debut", "date_fin"])

    proposal.save(update_fields=["updated_at"])
    return proposal


def update_poll_meta(
    proposal: DateProposal,
    *,
    title: str | None = None,
    description: str | None = None,
    audience: str | None = None,
) -> DateProposal:
    """Met à jour titre / description / audience (auteur ou staff)."""
    if proposal.status in (
        DateProposal.Status.LOCKED,
        DateProposal.Status.CANCELLED,
    ):
        raise ValueError("Ce sondage est clos — non modifiable.")

    fields: list[str] = ["updated_at"]
    if title is not None:
        cleaned = (title or "").strip()
        if not cleaned:
            raise ValueError("Titre requis.")
        proposal.title = cleaned[:200]
        fields.append("title")
    if description is not None:
        proposal.description = (description or "").strip()
        fields.append("description")
    if audience is not None:
        if audience not in DateProposal.Audience.values:
            raise ValueError("Audience invalide.")
        # Sans salon source, « membres du salon » n’a pas de sens.
        if (
            audience == DateProposal.Audience.ROOM
            and not proposal.source_room_id
            and not proposal.linked_event_id
        ):
            raise ValueError(
                "Ce sondage n’est pas lié à un salon — ouvrez-le à tous les musiciens."
            )
        proposal.audience = audience
        fields.append("audience")

    proposal.save(update_fields=fields)
    return proposal


def user_has_answered_poll(user, proposal: DateProposal) -> bool:
    """True si l’utilisateur a voté sur toutes les options du sondage."""
    options = list(proposal.options.all())
    if not options:
        return True
    option_ids = [o.pk for o in options]
    voted = (
        DateVote.objects.filter(user=user, option_id__in=option_ids)
        .values("option_id")
        .distinct()
        .count()
    )
    return voted >= len(option_ids)


def pending_polls_for_user(
    user,
    *,
    proposal_ids: list[int] | None = None,
    include_tallies: bool = True,
) -> list[DateProposal]:
    """
    Sondages OPEN accessibles à l’utilisateur et pas encore entièrement répondu.

    Attache ``proposal.banner_options`` quand ``include_tallies`` est vrai :
    liste de dicts
    ``{option, my_vote, counts, counts_json, counts_label}`` pour le vote
    inline de la bannière (totaux visibles par tous).
    """
    if not getattr(user, "is_authenticated", False):
        return []
    from users.roles import user_can_access_planning

    if not user_can_access_planning(user):
        return []

    is_staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    # Prefetch all votes: personal choice + tallies visible to everyone.
    options_qs = DateOption.objects.order_by("sort_order", "starts_at").prefetch_related(
        "votes"
    )
    qs = (
        DateProposal.objects.filter(status=DateProposal.Status.OPEN)
        .prefetch_related(Prefetch("options", queryset=options_qs))
        .select_related("linked_event")
        .order_by("-launched_at", "-created_at")
    )
    if proposal_ids is not None:
        if not proposal_ids:
            return []
        qs = qs.filter(pk__in=proposal_ids)
    if not is_staff:
        qs = qs.filter(_polls_accessible_q_for_user(user)).distinct()

    pending: list[DateProposal] = []
    for proposal in qs:
        if not is_staff and not user_can_access_poll(user, proposal):
            continue
        options = list(proposal.options.all())
        # ``options`` et leurs votes sont déjà prefetched. Ne pas refaire un
        # ``COUNT`` par sondage pour savoir si toutes les options sont votées.
        my_votes = {
            option.pk: next(
                (vote for vote in option.votes.all() if vote.user_id == user.pk),
                None,
            )
            for option in options
        }
        if not options or all(my_votes.values()):
            continue
        if not include_tallies:
            pending.append(proposal)
            continue
        banner_options = []
        for opt in options:
            my = my_votes[opt.pk]
            counts = vote_counts_for_option(opt)
            banner_options.append(
                {
                    "option": opt,
                    "my_vote": my.choice if my else None,
                    "counts": counts,
                    "counts_json": json.dumps(counts),
                    "counts_label": format_poll_vote_counts(counts),
                }
            )
        proposal.banner_options = banner_options
        pending.append(proposal)
    if proposal_ids is not None:
        positions = {proposal_id: position for position, proposal_id in enumerate(proposal_ids)}
        pending.sort(key=lambda proposal: positions.get(proposal.pk, len(positions)))
    return pending


POLL_VOTE_LABELS = {
    DateVote.Choice.YES: "Oui",
    DateVote.Choice.NO: "Non",
    DateVote.Choice.MAYBE: "Peut-être",
}


def _poll_vote_label(choice: str | None) -> str:
    if not choice:
        return ""
    return POLL_VOTE_LABELS.get(choice, "")


class CalendarPollMarker:
    """
    Entrée calendrier légère pour une DateOption d’un sondage OPEN.

    Expose les attributs attendus par ``upcoming_12_months.html`` (titre,
    cal_summary, etc.) sans créer d’Event.
    """

    def __init__(
        self,
        option: DateOption,
        proposal: DateProposal,
        *,
        my_vote: str | None = None,
        poll_answered: bool = False,
        vote_counts: dict[str, int] | None = None,
    ):
        self.pk = option.pk
        self.option_id = option.pk
        self.proposal_id = proposal.pk
        self.is_poll_option = True
        self.date_debut = option.starts_at
        label = (option.label or "").strip()
        self.titre = f"{proposal.title} — {label}" if label else proposal.title

        local = timezone.localtime(option.starts_at)
        lieu = ""
        event = proposal.linked_event
        if event is not None and event.venue_id:
            venue = event.venue
            if venue is not None:
                lieu = f"{venue.nom} — {venue.ville}" if venue.ville else venue.nom

        vote = (my_vote or "").strip()
        counts = vote_counts or {"yes": 0, "no": 0, "maybe": 0}
        linked = proposal.linked_event
        proposed_by_label = _user_display_label(getattr(proposal, "created_by", None))
        if not proposed_by_label and linked is not None:
            proposed_by_label = _user_display_label(getattr(linked, "proposed_by", None))
        self.cal_summary = {
            "titre": self.titre,
            "is_concert": False,
            "is_rehearsal": False,
            "is_proposal": True,
            "is_confirmed": False,
            "is_poll_option": True,
            "has_open_poll": True,
            "poll_id": proposal.pk,
            "open_poll_id": proposal.pk,
            "option_id": option.pk,
            "can_confirm_event": linked is not None,
            "my_poll_vote": vote,
            "my_poll_vote_label": _poll_vote_label(vote),
            "poll_answered": bool(poll_answered),
            "poll_vote_counts": counts,
            "poll_vote_counts_label": format_poll_vote_counts(counts),
            "statut": Event.Statut.TENTATIVE,
            "layer": "proposal",
            "kind_label": "Proposition",
            "type_nom": "Sondage de dates",
            "date_label": local.strftime("%d/%m/%Y"),
            "time_label": local.strftime("%H:%M"),
            "lieu": lieu,
            "proposed_by_label": proposed_by_label,
            "deadline_label": _deadline_label(proposal.deadline),
            "n_titulaires": 0,
            "n_remplacants": 0,
            "n_presents": 0,
            "n_maybe": 0,
            "maybe_detail": [],
            "instruments_manquants": [],
            "instruments_manquants_label": "—",
            "instruments_manquants_detail": [],
        }
        self.weather = None
        self.cal_chat = None
        self.cal_setlist = None


def open_poll_calendar_markers_for_user(
    user,
    *,
    range_start,
    range_end,
) -> list[CalendarPollMarker]:
    """
    Marqueurs « proposition » pour chaque DateOption des sondages OPEN
    accessibles à l’utilisateur, dans la fenêtre calendrier.
    """
    if not getattr(user, "is_authenticated", False):
        return []

    is_staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    options_qs = DateOption.objects.order_by("sort_order", "starts_at").prefetch_related(
        "votes"
    )
    qs = (
        DateProposal.objects.filter(status=DateProposal.Status.OPEN)
        .prefetch_related(Prefetch("options", queryset=options_qs))
        .select_related(
            "created_by",
            "linked_event",
            "linked_event__venue",
            "linked_event__proposed_by",
        )
    )
    if not is_staff:
        qs = qs.filter(_polls_accessible_q_for_user(user)).distinct()

    markers: list[CalendarPollMarker] = []
    for proposal in qs:
        if not user_can_access_poll(user, proposal):
            continue
        linked = proposal.linked_event
        linked_day = None
        linked_is_proposal = False
        linked_is_confirmed = False
        if linked is not None:
            linked_day = timezone.localtime(linked.date_debut).date()
            linked_statut = getattr(linked, "statut", "")
            linked_is_proposal = (not _is_rehearsal_type(linked)) and (
                linked_statut == Event.Statut.TENTATIVE
            )
            linked_is_confirmed = (not _is_rehearsal_type(linked)) and (
                linked_statut == Event.Statut.CONFIRME
            )
        # Événement déjà confirmé : plus de cartes « proposition / sondage ».
        if linked_is_confirmed:
            continue
        answered = user_has_answered_poll(user, proposal)
        for option in proposal.options.all():
            starts = option.starts_at
            if starts is None:
                continue
            if starts < range_start or starts > range_end:
                continue
            option_day = timezone.localtime(starts).date()
            # Évite le double marquage si l’événement lié tentative est déjà
            # affiché comme proposition le même jour.
            if linked_is_proposal and linked_day == option_day:
                continue
            my = next((v for v in option.votes.all() if v.user_id == user.pk), None)
            markers.append(
                CalendarPollMarker(
                    option,
                    proposal,
                    my_vote=my.choice if my else None,
                    poll_answered=answered,
                    vote_counts=vote_counts_for_option(option),
                )
            )
    return markers


def attach_open_poll_info_to_events(events, user) -> list:
    """
    Enrichit ``event.cal_summary`` quand un sondage OPEN est lié.

    Couvre le cas où le marqueur DateOption est omis (même jour que
    l’événement tentative) : le calendrier doit quand même montrer le
    statut de vote et un lien vers le sondage.
    """
    if not events or not getattr(user, "is_authenticated", False):
        return list(events)

    event_ids = [e.pk for e in events if getattr(e, "pk", None)]
    if not event_ids:
        return list(events)

    options_qs = DateOption.objects.order_by("sort_order", "starts_at").prefetch_related(
        "votes"
    )
    proposals = (
        DateProposal.objects.filter(
            status=DateProposal.Status.OPEN,
            linked_event_id__in=event_ids,
        )
        .prefetch_related(Prefetch("options", queryset=options_qs))
        .select_related("linked_event", "created_by")
    )
    by_event: dict[int, DateProposal] = {}
    for proposal in proposals:
        if user_can_access_poll(user, proposal):
            by_event[proposal.linked_event_id] = proposal

    for event in events:
        proposal = by_event.get(event.pk)
        if proposal is None:
            continue
        # Confirmé : le sondage de dates n’a plus sa place sur la fiche jour.
        if (
            not _is_rehearsal_type(event)
            and getattr(event, "statut", "") == Event.Statut.CONFIRME
        ):
            continue
        summary = dict(getattr(event, "cal_summary", None) or {})
        event_day = timezone.localtime(event.date_debut).date()
        options = list(proposal.options.all())
        matched = next(
            (
                opt
                for opt in options
                if opt.starts_at
                and timezone.localtime(opt.starts_at).date() == event_day
            ),
            next((o for o in options if o.starts_at), options[0] if options else None),
        )
        my_vote = None
        counts = {"yes": 0, "no": 0, "maybe": 0}
        if matched is not None:
            my = next((v for v in matched.votes.all() if v.user_id == user.pk), None)
            if my is not None:
                my_vote = my.choice
            counts = vote_counts_for_option(matched)
        vote = (my_vote or "").strip()
        summary["has_open_poll"] = True
        summary["open_poll_id"] = proposal.pk
        summary["poll_id"] = proposal.pk
        summary["can_confirm_event"] = True
        summary["my_poll_vote"] = vote
        summary["my_poll_vote_label"] = _poll_vote_label(vote)
        summary["poll_answered"] = user_has_answered_poll(user, proposal)
        summary["poll_vote_counts"] = counts
        summary["poll_vote_counts_label"] = format_poll_vote_counts(counts)
        if matched is not None:
            summary["option_id"] = matched.pk
        if not summary.get("proposed_by_label"):
            summary["proposed_by_label"] = _user_display_label(
                getattr(proposal, "created_by", None)
            ) or _user_display_label(getattr(event, "proposed_by", None))
        if proposal.deadline:
            summary["deadline_label"] = _deadline_label(proposal.deadline)
        event.cal_summary = summary
    return list(events)


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
    from users.nav_cache import invalidate_nav_banner_cache

    invalidate_nav_banner_cache(user)
    try:
        from users.notify import mark_notifications_responded

        mark_notifications_responded(
            user,
            related_type="proposal",
            related_id=proposal.pk,
        )
    except Exception:
        logger.exception(
            "Échec mark responded proposal_id=%s user_id=%s",
            proposal.pk,
            getattr(user, "pk", None),
        )
    return vote


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


def open_proposal_for_event(event) -> DateProposal | None:
    """Sondage ouvert lié à l’événement (votes en cours, date à confirmer)."""
    return (
        DateProposal.objects.filter(
            linked_event=event,
            status=DateProposal.Status.OPEN,
        )
        .prefetch_related(
            Prefetch(
                "options",
                queryset=DateOption.objects.order_by("sort_order", "starts_at"),
            )
        )
        .order_by("-launched_at", "-created_at")
        .first()
    )
