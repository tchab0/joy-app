"""Helpers métier planning — module interne."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from types import SimpleNamespace

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
from planning.services.constants import RESPOND_MAP
from planning.services.status import get_status

def _parse_maybe_remind_at(value) -> date | None:
    """Accepte date, datetime ou chaîne ISO (YYYY-MM-DD)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = parse_date(value.strip())
        if parsed is None:
            raise ValueError("Date de relance invalide.")
        return parsed
    raise ValueError("Date de relance invalide.")


def apply_maybe_remind_schedule(
    participation: EventParticipation,
    *,
    remind_at: date | None = None,
    remind_weekly: bool = False,
) -> None:
    """
    Planifie la prochaine relance pour un « peut-être ».

    - Date choisie → rappel à cette date, puis hebdo tant que le statut reste maybe.
    - « Je ne sais pas » (remind_weekly, sans date) → première relance dans 7 jours.
    """
    today = timezone.localdate()
    event_day = timezone.localtime(participation.event.date_debut).date()
    participation.maybe_last_reminded_at = None

    if remind_at is not None:
        if remind_at < today:
            raise ValueError("La date de relance ne peut pas être dans le passé.")
        if remind_at > event_day:
            raise ValueError(
                "La date de relance doit être avant ou le jour de l’événement."
            )
        participation.maybe_remind_at = remind_at
        # Après la date choisie, on continue chaque semaine si toujours « peut-être ».
        participation.maybe_remind_weekly = True
    elif remind_weekly:
        participation.maybe_remind_at = today + timedelta(days=7)
        if participation.maybe_remind_at > event_day:
            participation.maybe_remind_at = event_day
        participation.maybe_remind_weekly = True
    else:
        # Défaut : hebdomadaire (si le client n’envoie rien).
        participation.maybe_remind_at = today + timedelta(days=7)
        if participation.maybe_remind_at > event_day:
            participation.maybe_remind_at = event_day
        participation.maybe_remind_weekly = True


def clear_maybe_remind_schedule(participation: EventParticipation) -> None:
    participation.maybe_remind_at = None
    participation.maybe_remind_weekly = False
    participation.maybe_last_reminded_at = None


def set_participation_response(
    participation: EventParticipation,
    response: str,
    *,
    comment: str = "",
    maybe_remind_at=None,
    maybe_remind_weekly: bool | None = None,
) -> EventParticipation:
    if response not in RESPOND_MAP:
        raise ValueError("Réponse invalide")
    old_code = participation.status.code if participation.status_id else None
    new_code = RESPOND_MAP[response]
    comment = (comment or "").strip()
    # Dispo → Non (invalidation) ok ; Dispo → Peut-être interdit.
    if old_code == "confirmed" and new_code == "maybe":
        raise ValueError(
            "Une présence confirmée ne peut pas passer en « peut-être »."
        )
    leaving_confirmed = old_code == "confirmed" and new_code == "declined"
    participation.status = get_status(new_code)
    if comment:
        participation.comment = comment

    update_fields = ["status", "comment", "updated_at"]
    if new_code == "maybe":
        remind_date = _parse_maybe_remind_at(maybe_remind_at)
        weekly = bool(maybe_remind_weekly) if maybe_remind_weekly is not None else (
            remind_date is None
        )
        apply_maybe_remind_schedule(
            participation,
            remind_at=remind_date,
            remind_weekly=weekly,
        )
        update_fields.extend(
            ["maybe_remind_at", "maybe_remind_weekly", "maybe_last_reminded_at"]
        )
    else:
        clear_maybe_remind_schedule(participation)
        update_fields.extend(
            ["maybe_remind_at", "maybe_remind_weekly", "maybe_last_reminded_at"]
        )

    participation.save(update_fields=update_fields)
    if leaving_confirmed:
        notify_staff_presence_invalidated(
            participation, old_code=old_code, new_code=new_code
        )
    try:
        from users.notify import mark_notifications_responded

        mark_notifications_responded(
            participation.user,
            related_any=[
                ("participation", participation.pk),
                ("event", participation.event_id),
            ],
        )
    except Exception:
        logger.exception(
            "Échec mark responded participation_id=%s", participation.pk
        )
    return participation


def notify_maybe_remind(participation: EventParticipation) -> int:
    """Relance le musicien pour qu’il tranche Oui / Peut-être / Non."""
    event = participation.event
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    poste = participation.poste_label
    poste_bit = f" — {poste}" if poste and poste != "—" else ""
    body = (
        f"Toujours en « peut-être » pour « {event.titre} » "
        f"({date_label}{poste_bit}). "
        f"Pouvez-vous confirmer ou décliner ?"
    )
    try:
        url = reverse("planning:event_detail", kwargs={"pk": event.pk})
    except Exception:
        url = "/planning/moi/"
    try:
        return notify_users(
            [participation.user],
            title="JOY — Relance disponibilité",
            body=body,
            url=url,
            requires_response=True,
            related_type="participation",
            related_id=participation.pk,
            notify_type="participation",
        )
    except Exception:
        logger.exception(
            "Échec relance maybe participation_id=%s", participation.pk
        )
        return 0


def send_due_maybe_reminds(
    *,
    as_of: date | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Envoie les relances « peut-être » dues.

    Retourne (nb participations traitées, nb notifications envoyées).
    """
    today = as_of or timezone.localdate()
    now = timezone.now()
    qs = (
        EventParticipation.objects.filter(
            status__code="maybe",
            maybe_remind_at__isnull=False,
            maybe_remind_at__lte=today,
            event__date_debut__gte=now,
        )
        .exclude(event__statut=Event.Statut.ANNULE)
        .select_related("event", "user", "status")
        .order_by("maybe_remind_at", "pk")
    )
    treated = 0
    sent = 0
    for part in qs:
        treated += 1
        if dry_run:
            continue
        sent += notify_maybe_remind(part)
        part.maybe_last_reminded_at = now
        if part.maybe_remind_weekly:
            event_day = timezone.localtime(part.event.date_debut).date()
            nxt = today + timedelta(days=7)
            part.maybe_remind_at = nxt if nxt <= event_day else None
        else:
            part.maybe_remind_at = None
        part.save(
            update_fields=[
                "maybe_remind_at",
                "maybe_last_reminded_at",
                "updated_at",
            ]
        )
    return treated, sent


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
    staff = User.objects.filter(is_active=True, is_staff=True).exclude(
        pk=musician.pk
    )
    try:
        return notify_users(
            staff,
            title="JOY — Présence annulée",
            body=" ".join(body_bits),
            url=url,
            related_type="staff_alert",
            related_id=participation.pk,
            notify_type="staff_alert",
        )
    except Exception:
        logger.exception(
            "Échec notif staff présence invalidée participation_id=%s",
            participation.pk,
        )
        return 0


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


class BoardRow:
    """Ligne « Mes dates » : participation réelle ou date encore sans réponse."""

    __slots__ = ("event", "participation", "pk", "status", "poste")

    def __init__(self, event, participation: EventParticipation | None = None):
        self.event = event
        self.participation = participation
        if participation is not None:
            self.pk = participation.pk
            self.status = participation.status
            self.poste = participation.poste
        else:
            self.pk = None
            self.status = SimpleNamespace(
                code="invited",
                label="À répondre",
                color_token="warning",
            )
            self.poste = ""

    @property
    def poste_label(self) -> str:
        if self.participation is not None:
            return self.participation.poste_label
        return ""


def board_rows_for_user(user, *, limit: int = 40) -> list[BoardRow]:
    """
    Toutes les dates à venir (confirmées ou non), pour positionnement libre.

    Plus besoin d’avoir été invité : une ligne sans participation = « À répondre ».
    """
    now = timezone.now()
    events = list(
        Event.objects.filter(
            date_debut__gte=now,
            statut__in=[Event.Statut.CONFIRME, Event.Statut.TENTATIVE],
        )
        .select_related("venue", "type")
        .order_by("date_debut")[:limit]
    )
    if not events:
        return []
    parts = {
        p.event_id: p
        for p in EventParticipation.objects.filter(
            user=user, event_id__in=[e.pk for e in events]
        ).select_related("status")
    }
    return [BoardRow(event, parts.get(event.pk)) for event in events]


