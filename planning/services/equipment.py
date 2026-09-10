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

from planning.services.constants import DEFAULT_BIG_BAND_EQUIPMENT, EQUIPMENT_CATEGORIES

def ensure_default_equipment(*, force: bool = False) -> list[EquipmentItem]:
    """Crée / met à jour le catalogue matériel big band (idempotent)."""
    existing = {
        item.name.casefold(): item
        for item in EquipmentItem.objects.filter(
            name__in=[name for name, _, _ in DEFAULT_BIG_BAND_EQUIPMENT]
        )
    }
    if len(existing) == len(DEFAULT_BIG_BAND_EQUIPMENT) and not force:
        stale = False
        for name, category, order in DEFAULT_BIG_BAND_EQUIPMENT:
            item = existing.get(name.casefold())
            if item is None:
                stale = True
                break
            if (
                item.category != category
                or item.sort_order != order
                or not item.is_active
            ):
                stale = True
                break
        if not stale:
            return list(
                EquipmentItem.objects.filter(is_active=True).order_by(
                    "sort_order", "name"
                )
            )

    for name, category, order in DEFAULT_BIG_BAND_EQUIPMENT:
        EquipmentItem.objects.update_or_create(
            name=name,
            defaults={
                "category": category,
                "sort_order": order,
                "is_active": True,
            },
        )
    return list(
        EquipmentItem.objects.filter(is_active=True).order_by("sort_order", "name")
    )


def get_or_create_equipment_item(
    name: str,
    *,
    category: str = "",
) -> EquipmentItem:
    """Résout un matériel catalogue par nom (création si besoin)."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Nom de matériel requis.")
    cat = (category or "").strip()
    if cat not in EQUIPMENT_CATEGORIES:
        raise ValueError("Catégorie invalide.")
    existing = (
        EquipmentItem.objects.filter(name__iexact=cleaned)
        .order_by("pk")
        .first()
    )
    if existing is not None:
        updates: list[str] = []
        if not existing.is_active:
            existing.is_active = True
            updates.append("is_active")
        if existing.category != cat:
            existing.category = cat
            updates.append("category")
        if updates:
            existing.save(update_fields=updates)
        return existing
    return EquipmentItem.objects.create(
        name=cleaned,
        category=cat,
        sort_order=900,
        is_active=True,
    )


def suggest_event_equipment(
    event: Event,
    user,
    *,
    item_id: str = "",
    item_name: str = "",
    note: str = "",
) -> EventEquipmentAssignment:
    """
    Proposition musicien : ajoute (ou annote) un matériel sur la date.
    Ne crée pas d’assignation « apporté par » — le staff décide ensuite.
    """
    from planning.models import EventEquipmentAssignment

    item_id = (item_id or "").strip()
    item_name = (item_name or "").strip()
    note = (note or "").strip()

    if item_id and item_id != "__new__":
        item = get_object_or_404(EquipmentItem, pk=item_id, is_active=True)
    elif item_name:
        # Proposition libre : réutilise un item homonyme s’il existe, sinon Divers.
        existing = (
            EquipmentItem.objects.filter(name__iexact=item_name)
            .order_by("pk")
            .first()
        )
        if existing is not None:
            if not existing.is_active:
                existing.is_active = True
                existing.save(update_fields=["is_active"])
            item = existing
        else:
            item = get_or_create_equipment_item(item_name, category="Divers")
    else:
        raise ValueError("Choisissez un matériel ou indiquez une proposition.")

    who = (user.get_full_name() or user.get_username() or "musicien").strip()
    prefix = f"Proposé par {who}"
    detail = f"{prefix} — {note}" if note else prefix
    detail = detail[:255]

    assignment, created = EventEquipmentAssignment.objects.get_or_create(
        event=event,
        item=item,
        defaults={
            "status": EventEquipmentAssignment.Status.NEEDED,
            "notes": detail,
        },
    )
    if not created:
        # Déjà listé : conserver l’assignation, enrichir les notes.
        existing_notes = (assignment.notes or "").strip()
        if detail not in existing_notes:
            assignment.notes = (
                f"{existing_notes} · {detail}".strip(" ·")[:255]
                if existing_notes
                else detail
            )
            assignment.save(update_fields=["notes"])
    return assignment


