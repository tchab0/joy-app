"""Helpers métier pour les répétitions."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from django.db import OperationalError, ProgrammingError, transaction
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventType, Venue
from planning.models import EventParticipation
from planning.services import (
    eligible_substitutes_for,
    ensure_participation_statuses,
    get_status,
    propose_substitute,
    titulaires_queryset,
)
from repertoire.models import Piece
from repetitions.models import RehearsalItem, RehearsalPlan
from users.notify import notify_users

logger = logging.getLogger(__name__)

REHEARSAL_TYPE_NAME = "Répétition"


def get_or_create_rehearsal_type() -> EventType:
    obj, _ = EventType.objects.get_or_create(nom=REHEARSAL_TYPE_NAME)
    return obj


def is_rehearsal_event(event: Event) -> bool:
    return bool(getattr(event, "is_rehearsal", False))


def get_or_create_plan(event: Event, *, user=None) -> RehearsalPlan:
    plan, created = RehearsalPlan.objects.get_or_create(event=event)
    if created and user is not None:
        plan.updated_by = user
        plan.save(update_fields=["updated_by", "updated_at"])
    return plan


def sync_roadmap_items(
    plan: RehearsalPlan,
    ordered_piece_ids: list[int],
    notes_by_piece: dict[int, str] | None = None,
) -> None:
    """Remplace l’ordre des morceaux (positions 1..n)."""
    notes_by_piece = notes_by_piece or {}
    seen: set[int] = set()
    unique_ids: list[int] = []
    for pid in ordered_piece_ids:
        if pid in seen:
            continue
        seen.add(pid)
        unique_ids.append(pid)

    valid_ids = set(
        Piece.objects.filter(pk__in=unique_ids).values_list("pk", flat=True)
    )
    unique_ids = [pid for pid in unique_ids if pid in valid_ids]

    plan.items.exclude(piece_id__in=unique_ids).delete()
    existing = {item.piece_id: item for item in plan.items.all()}
    for pos, pid in enumerate(unique_ids, start=1):
        note = (notes_by_piece.get(pid) or "").strip()[:300]
        item = existing.get(pid)
        if item is None:
            RehearsalItem.objects.create(
                plan=plan, piece_id=pid, position=pos, note=note
            )
        else:
            if item.position != pos or item.note != note:
                item.position = pos
                item.note = note
                item.save(update_fields=["position", "note"])


def confirm_titulaires_to_rehearsal(
    event: Event,
    *,
    send_notification: bool = False,
) -> int:
    """
    Inscrit tous les titulaires comme présents (confirmed) sur une répé.
    Ignore les déjà inscrits.
    """
    ensure_participation_statuses()
    confirmed = get_status("confirmed")
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
                status=confirmed,
                poste=poste,
                role_kind=EventParticipation.RoleKind.TITULAIRE,
            )
        )
    if not to_create:
        return 0

    EventParticipation.objects.bulk_create(to_create, ignore_conflicts=True)
    try:
        from chat.services import sync_participation_to_chat

        created_parts = list(
            EventParticipation.objects.filter(
                event=event, user_id__in=[p.user_id for p in to_create]
            ).select_related("user")
        )
        for part in created_parts:
            sync_participation_to_chat(part)
        if send_notification:
            notify_rehearsal_created(event, [p.user for p in created_parts])
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Sync chat / notif répé ignorée: %s", exc)
    return len(to_create)


def notify_rehearsal_created(event: Event, users) -> int:
    users = list(users)
    if not users:
        return 0
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    url = reverse("repetitions:detail", kwargs={"pk": event.pk})
    body = (
        f"Nouvelle répétition : « {event.titre} » ({date_label}). "
        f"Vous êtes attendu·e — signalez une absence si besoin."
    )
    return notify_users(
        users,
        title="JOY — Répétition",
        body=body,
        url=url,
    )


@transaction.atomic
def create_rehearsal(
    *,
    titre: str,
    venue: Venue,
    date_debut: datetime,
    date_fin: datetime | None = None,
    description: str = "",
    notes: str = "",
    created_by=None,
    piece_ids: list[int] | None = None,
    notes_by_piece: dict[int, str] | None = None,
    notify_musicians: bool = False,
) -> tuple[Event, RehearsalPlan]:
    """Crée l’Event répétition + feuille de route + titulaires présents."""
    titre = (titre or "").strip()
    if not titre:
        raise ValueError("Titre requis")
    if venue is None:
        raise ValueError("Lieu requis")

    event_type = get_or_create_rehearsal_type()
    event = Event(
        titre=titre,
        type=event_type,
        venue=venue,
        date_debut=date_debut,
        date_fin=date_fin,
        description=(description or "").strip(),
        statut=Event.Statut.CONFIRME,
        public=False,
    )
    event._skip_titulaire_invite = True
    event.save()

    plan = RehearsalPlan.objects.create(
        event=event,
        notes=(notes or "").strip(),
        updated_by=created_by,
    )
    if piece_ids:
        sync_roadmap_items(plan, piece_ids, notes_by_piece)

    confirm_titulaires_to_rehearsal(event, send_notification=notify_musicians)
    return event, plan


def set_rehearsal_absence(
    participation: EventParticipation,
    *,
    absent: bool,
) -> EventParticipation:
    """Présent par défaut (confirmed) ; absent = declined."""
    if not is_rehearsal_event(participation.event):
        raise ValueError("Cet événement n’est pas une répétition")
    ensure_participation_statuses()
    participation.status = get_status("declined" if absent else "confirmed")
    if not absent and participation.comment == "Absent à la répétition":
        participation.comment = ""
    elif absent and not participation.comment:
        participation.comment = "Absent à la répétition"
    participation.save(update_fields=["status", "comment", "updated_at"])
    return participation


def notify_substitute_for_absence(
    participation: EventParticipation,
    candidate,
    *,
    note: str = "",
) -> int:
    """Propose un remplaçant + notification (action staff manuelle)."""
    req = propose_substitute(participation, candidate, note=note)
    local = timezone.localtime(participation.event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    titulaire = participation.user.get_full_name() or participation.user.username
    poste = participation.poste_label
    url = reverse("repetitions:detail", kwargs={"pk": participation.event_id})
    body = (
        f"Remplacement proposé pour « {participation.event.titre} » "
        f"({date_label}) — poste {poste}, à la place de {titulaire}."
    )
    return notify_users(
        [candidate],
        title="JOY — Remplacement répé",
        body=body,
        url=url,
    )


def attendance_for_event(event: Event) -> dict:
    """Répartition présents / absents pour l’affichage staff."""
    parts = list(
        EventParticipation.objects.filter(event=event)
        .select_related("user", "status", "user__musician_profile__section")
        .order_by("user__last_name", "user__first_name")
    )
    present = []
    absent = []
    other = []
    by_section_present: dict[str, list] = defaultdict(list)
    section_order: dict[str, int] = {}

    for p in parts:
        code = p.status.code
        section = p.section_for_roster()
        section_name = section.name if section else "Sans pupitre"
        if section_name not in section_order:
            section_order[section_name] = section.sort_order if section else 999

        if code == "confirmed":
            present.append(p)
            by_section_present[section_name].append(p)
        elif code in ("declined", "replacement_needed"):
            absent.append(p)
        else:
            other.append(p)

    ordered_sections = {
        name: by_section_present[name]
        for name in sorted(
            by_section_present.keys(),
            key=lambda n: (section_order.get(n, 999), n),
        )
    }
    return {
        "present": present,
        "absent": absent,
        "other": other,
        "by_section_present": ordered_sections,
        "n_present": len(present),
        "n_absent": len(absent),
    }


def absent_with_eligible_subs(event: Event) -> list[dict]:
    """Absents titulaires + candidats remplaçants pour CTA staff."""
    attendance = attendance_for_event(event)
    rows = []
    for p in attendance["absent"]:
        if p.role_kind == EventParticipation.RoleKind.REMPLACANT:
            continue
        rows.append(
            {
                "participation": p,
                "eligible": eligible_substitutes_for(p),
            }
        )
    return rows
