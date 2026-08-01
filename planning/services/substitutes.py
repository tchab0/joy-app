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
from planning.services.rsvp import set_participation_response
from planning.services.status import get_status

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


