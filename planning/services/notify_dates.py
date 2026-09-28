"""Fenêtre d’envoi : jamais de notification pour une date déjà passée."""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

# Inbox dont l’objet lié est un événement (date = date_debut).
# « photos » est exclu : le rappel J+7 est volontairement après la date.
EVENT_RELATED_TYPES = frozenset(
    {"event", "event_roadmap", "rehearsal"}
)


def calendar_date(value) -> date | None:
    """Date locale d’un datetime ou date. None si vide."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value).date()
    if isinstance(value, date):
        return value
    return None


def is_past_calendar_date(value, *, today: date | None = None) -> bool:
    """True si la date locale est strictement avant aujourd’hui."""
    day = calendar_date(value)
    if day is None:
        return False
    if today is None:
        today = timezone.localdate()
    return day < today


def is_past_event(event, *, today: date | None = None) -> bool:
    """True si l’événement a une date de début déjà dépassée."""
    if event is None:
        return False
    return is_past_calendar_date(getattr(event, "date_debut", None), today=today)


def proposal_has_only_past_dates(proposal, *, today: date | None = None) -> bool:
    """
    True si le sondage ne porte plus que sur des dates dépassées.

    Une option ou un événement lié encore à venir (aujourd’hui inclus) garde
    le sondage notifiable. Un sondage sans date n’est pas « dépassé ».
    """
    if today is None:
        today = timezone.localdate()
    option_days: list[date] = []
    for opt in proposal.options.all():
        day = calendar_date(getattr(opt, "starts_at", None))
        if day is not None:
            option_days.append(day)
    if any(day >= today for day in option_days):
        return False
    event = getattr(proposal, "linked_event", None)
    if event is not None and not is_past_event(event, today=today):
        return False
    if option_days:
        return True
    return event is not None and is_past_event(event, today=today)


def past_notification_keys(items, *, today: date | None = None) -> set[tuple[str, int]]:
    """
    Clés (related_type, related_id) dont la date est dépassée.

    Un objet introuvable n’est pas considéré comme dépassé.
    """
    if today is None:
        today = timezone.localdate()

    event_pairs: list[tuple[str, int]] = []
    part_pairs: list[tuple[str, int]] = []
    proposal_pairs: list[tuple[str, int]] = []
    event_ids: set[int] = set()
    part_ids: set[int] = set()
    proposal_ids: set[int] = set()

    for item in items:
        rid = getattr(item, "related_id", None)
        rtype = (getattr(item, "related_type", None) or "").strip()
        if not rid or not rtype:
            continue
        rid = int(rid)
        if rtype in EVENT_RELATED_TYPES:
            event_pairs.append((rtype, rid))
            event_ids.add(rid)
        elif rtype in {"participation", "staff_alert"}:
            part_pairs.append((rtype, rid))
            part_ids.add(rid)
        elif rtype == "proposal":
            proposal_pairs.append((rtype, rid))
            proposal_ids.add(rid)

    past: set[tuple[str, int]] = set()
    if not (event_ids or part_ids or proposal_ids):
        return past

    from events.models import Event
    from planning.models import DateProposal, EventParticipation

    if event_ids:
        events = {
            row.pk: row
            for row in Event.objects.filter(pk__in=event_ids).only("pk", "date_debut")
        }
        for rtype, rid in event_pairs:
            if is_past_event(events.get(rid), today=today):
                past.add((rtype, rid))

    if part_ids:
        parts = EventParticipation.objects.filter(pk__in=part_ids).select_related(
            "event"
        )
        by_id = {part.pk: part for part in parts}
        for rtype, rid in part_pairs:
            part = by_id.get(rid)
            event = part.event if part is not None else None
            if is_past_event(event, today=today):
                past.add((rtype, rid))

    if proposal_ids:
        proposals = DateProposal.objects.filter(pk__in=proposal_ids).select_related(
            "linked_event"
        ).prefetch_related("options")
        by_id = {proposal.pk: proposal for proposal in proposals}
        for rtype, rid in proposal_pairs:
            proposal = by_id.get(rid)
            if proposal is not None and proposal_has_only_past_dates(
                proposal, today=today
            ):
                past.add((rtype, rid))

    return past


def system_message_event_is_past(message, *, today: date | None = None) -> bool:
    """
    Message système lié à un événement dont la date est dépassée.

    Utilise l’événement déjà chargé (fil ou salon). Pas de requête supplémentaire.
    """
    from chat.models import ChatMessage

    if getattr(message, "kind", None) != ChatMessage.Kind.SYSTEM:
        return False
    event = getattr(message, "thread_event", None)
    if event is None:
        room = getattr(message, "room", None)
        event = getattr(room, "event", None) if room is not None else None
    return is_past_event(event, today=today)
