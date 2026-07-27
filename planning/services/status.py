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

from planning.services import constants as _constants
from planning.services.constants import STATUS_CODES

def ensure_participation_statuses(*, force: bool = False) -> dict[str, ParticipationStatus]:
    if _constants._STATUS_CACHE is not None and not force:
        return _constants._STATUS_CACHE

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
            _constants._STATUS_CACHE = existing
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
    _constants._STATUS_CACHE = result
    return result


def get_status(code: str) -> ParticipationStatus:
    statuses = ensure_participation_statuses()
    return statuses[code]


