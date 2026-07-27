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
from django.utils.dateparse import parse_date

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
from planning.services.invites import invite_titulaires_to_event, notify_event_invite, titulaires_queryset
from planning.services.rsvp import get_participation_for

def poll_notification_recipients(proposal: DateProposal) -> list:
    """
    Musiciens concernés par un sondage : membres actifs du salon
    + participations événement (sans exclure le lanceur).
    """
    event = proposal.linked_event
    if event is None:
        return []
    from chat.models import ChatMembership
    from chat.services import ensure_event_room

    room = ensure_event_room(event)
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
    return list(by_id.values())


def notify_availability_poll(proposal: DateProposal) -> int:
    """Envoie (ou renvoie) les notifications de sondage aux destinataires."""
    users = poll_notification_recipients(proposal)
    poll_path = reverse("planning:poll_detail", kwargs={"pk": proposal.pk})
    deadline_bit = ""
    if proposal.deadline:
        deadline_bit = f" Répondez avant le {proposal.deadline.strftime('%d/%m/%Y')}."
    return notify_users(
        users,
        title="JOY — Sondage disponibilité",
        body=(
            f"Sondage dispo : « {proposal.title} ».{deadline_bit} "
            f"Répondez dans le planning / salon."
        ),
        url=poll_path,
        requires_response=True,
        related_type="proposal",
        related_id=proposal.pk,
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
    deadline_label = proposal.deadline.strftime("%d/%m/%Y") if proposal.deadline else ""
    deadline_bit = f" avant le {deadline_label}" if deadline_label else ""
    try:
        return notify_users(
            users,
            title="JOY — Rappel sondage",
            body=(
                f"Rappel : sondage « {proposal.title} » — "
                f"répondez{deadline_bit}. "
                f"Répondez dans le planning / salon."
            ),
            url=poll_path,
            requires_response=True,
            related_type="proposal",
            related_id=proposal.pk,
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
    Autorise / lance le sondage : statut OPEN, message mis en évidence dans
    le salon, alerte (push ou e-mail) aux musiciens du salon / roster.
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
        from chat.models import ChatMessage
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
        notify_availability_poll(proposal)

    return proposal


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


def format_poll_vote_counts(counts: dict[str, int] | None) -> str:
    """Libellé court visible par tous : Oui / Non / Peut-être."""
    c = counts or {}
    return (
        f"Oui {int(c.get('yes', 0))} · "
        f"Non {int(c.get('no', 0))} · "
        f"Peut-être {int(c.get('maybe', 0))}"
    )


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


def user_can_edit_poll_deadline(user, proposal: DateProposal) -> bool:
    """Auteur du sondage ou staff."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    return proposal.created_by_id == getattr(user, "pk", None)


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


def pending_polls_for_user(user) -> list[DateProposal]:
    """
    Sondages OPEN accessibles à l’utilisateur et pas encore entièrement répondu.

    Attache ``proposal.banner_options`` : liste de dicts
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
    if not is_staff:
        qs = qs.filter(
            linked_event__isnull=False,
            linked_event__participations__user=user,
        ).distinct()

    pending: list[DateProposal] = []
    for proposal in qs:
        if not user_can_access_poll(user, proposal):
            continue
        if user_has_answered_poll(user, proposal):
            continue
        banner_options = []
        for opt in proposal.options.all():
            my = next((v for v in opt.votes.all() if v.user_id == user.pk), None)
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
        qs = qs.filter(
            linked_event__isnull=False,
            linked_event__participations__user=user,
        ).distinct()

    markers: list[CalendarPollMarker] = []
    for proposal in qs:
        if not user_can_access_poll(user, proposal):
            continue
        linked = proposal.linked_event
        linked_day = None
        linked_is_proposal = False
        if linked is not None:
            linked_day = timezone.localtime(linked.date_debut).date()
            linked_is_proposal = (not _is_rehearsal_type(linked)) and (
                getattr(linked, "statut", "") == Event.Statut.TENTATIVE
            )
        answered = user_has_answered_poll(user, proposal)
        for option in proposal.options.all():
            starts = option.starts_at
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
        summary = dict(getattr(event, "cal_summary", None) or {})
        event_day = timezone.localtime(event.date_debut).date()
        options = list(proposal.options.all())
        matched = next(
            (
                opt
                for opt in options
                if timezone.localtime(opt.starts_at).date() == event_day
            ),
            options[0] if options else None,
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
