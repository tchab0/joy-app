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

from planning.services.substitutes import (
    _remplacant_any_q,
    _remplacant_in_postes_q,
    _remplacant_matches_poste_q,
)

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


def roster_by_stage(parts) -> dict:
    """
    Effectif admin disposé comme sur scène (chaises vides incluses).

    Retourne :
    - rows : 4 rangées de cellules ``{poste, label, parts}``
    - extras : postes hors scène (ex. percussion) avec au moins une participation
    - unassigned : participations sans poste
    """
    labels = dict(MusicianProfile.Poste.choices)
    stage_postes: set[str] = set()
    for row in MusicianProfile.POSTE_STAGE_ROWS:
        stage_postes.update(row)

    by_poste: dict[str, list] = defaultdict(list)
    unassigned: list = []
    for p in parts:
        if p.poste:
            by_poste[p.poste].append(p)
        else:
            unassigned.append(p)

    rows = [
        [
            {
                "poste": poste,
                "label": labels.get(poste, poste),
                "parts": by_poste.get(poste, []),
            }
            for poste in row
        ]
        for row in MusicianProfile.POSTE_STAGE_ROWS
    ]

    extras = [
        {
            "poste": code,
            "label": labels.get(code, code),
            "parts": by_poste[code],
        }
        for code, _label in MusicianProfile.Poste.choices
        if code not in stage_postes and by_poste.get(code)
    ]
    return {"rows": rows, "extras": extras, "unassigned": unassigned}


def remplacants_for_poste(
    poste: str,
    *,
    taken_user_ids: set[int] | None = None,
) -> list[dict]:
    """
    Remplaçants déclarés pour une chaise précise (hors déjà pris sur l’événement).

    Chaque entrée : user_id, name, poste, invite_slot (« user_id:poste »).
    """
    poste = (poste or "").strip()
    if not poste:
        return []
    taken = taken_user_ids or set()
    profiles = (
        MusicianProfile.objects.select_related("user")
        .filter(user__is_active=True, user__is_musician=True)
        .filter(_remplacant_matches_poste_q(poste))
        .order_by("user__last_name", "user__first_name")
    )
    out: list[dict] = []
    for profile in profiles:
        if profile.user_id in taken:
            continue
        name = profile.user.get_full_name() or profile.user.username
        out.append(
            {
                "user_id": profile.user_id,
                "name": name,
                "poste": poste,
                "invite_slot": f"{profile.user_id}:{poste}",
            }
        )
    return out


def attach_roster_substitutes(stage: dict, *, taken_user_ids: set[int]) -> dict:
    """Ajoute needs_substitute + eligible (remp. par chaise) aux cellules du stage."""

    def enrich(cell: dict) -> None:
        parts = cell.get("parts") or []
        needs = not any(
            getattr(getattr(p, "status", None), "code", None) == "confirmed"
            for p in parts
        )
        cell["needs_substitute"] = needs
        cell["eligible"] = (
            remplacants_for_poste(cell.get("poste") or "", taken_user_ids=taken_user_ids)
            if needs
            else []
        )

    for row in stage.get("rows") or []:
        for cell in row:
            enrich(cell)
    for cell in stage.get("extras") or []:
        enrich(cell)
    return stage


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


