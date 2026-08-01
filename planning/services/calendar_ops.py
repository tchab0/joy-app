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

from planning.services.roster import _expected_sections, remplacants_by_section_code


def _is_concert_type(event) -> bool:
    nom = (getattr(getattr(event, "type", None), "nom", None) or "").strip().lower()
    return "concert" in nom


def _is_rehearsal_type(event) -> bool:
    return bool(getattr(event, "is_rehearsal", False))


def _user_display_label(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or "").strip() or user.username or ""


def _deadline_label(deadline) -> str:
    if deadline is None:
        return ""
    if hasattr(deadline, "strftime"):
        return deadline.strftime("%d/%m/%Y")
    return str(deadline)


def _linked_proposal_meta(event) -> tuple[str, str]:
    """
    Retourne (proposed_by_label, deadline_label) pour un Event.

    Prefer ``proposed_by`` sur l’événement ; deadline depuis un sondage lié
    (prefetch ``from_proposals`` si présent).
    """
    proposed_by_label = _user_display_label(getattr(event, "proposed_by", None))
    deadline_label = ""
    proposals = getattr(event, "from_proposals", None)
    if proposals is None:
        return proposed_by_label, deadline_label
    related = list(proposals.all())
    # Prefer OPEN, then DRAFT, then any with a deadline / author.
    related.sort(
        key=lambda p: (
            0 if getattr(p, "status", "") == "open"
            else 1 if getattr(p, "status", "") == "draft"
            else 2
        )
    )
    for proposal in related:
        if not proposed_by_label:
            proposed_by_label = _user_display_label(getattr(proposal, "created_by", None))
        if not deadline_label and proposal.deadline:
            deadline_label = _deadline_label(proposal.deadline)
        if proposed_by_label and deadline_label:
            break
    return proposed_by_label, deadline_label


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
    remplacants_idx = remplacants_by_section_code()
    by_event_confirmed: dict[int, list] = defaultdict(list)
    by_event_maybe: dict[int, list] = defaultdict(list)
    by_event_taken: dict[int, set[int]] = defaultdict(set)

    parts = (
        EventParticipation.objects.filter(
            event_id__in=[e.pk for e in events],
            status__code__in=["confirmed", "invited", "maybe"],
        )
        .select_related("user__musician_profile__section", "status")
        .order_by("pk")
    )
    for p in parts:
        by_event_taken[p.event_id].add(p.user_id)
        if p.status.code == "confirmed":
            by_event_confirmed[p.event_id].append(p)
        elif p.status.code == "maybe":
            by_event_maybe[p.event_id].append(p)

    summaries: dict[int, dict] = {}
    for event in events:
        confirmed = by_event_confirmed.get(event.pk, [])
        maybes = by_event_maybe.get(event.pk, [])
        n_tit = 0
        n_rem = 0
        covered_section_ids: set[int] = set()
        for p in confirmed:
            try:
                profile = p.user.musician_profile
            except MusicianProfile.DoesNotExist:
                profile = None
            if p.role_kind == EventParticipation.RoleKind.REMPLACANT:
                n_rem += 1
            elif p.role_kind == EventParticipation.RoleKind.TITULAIRE:
                n_tit += 1
            elif (
                profile is not None
                and profile.is_remplacant
                and not profile.is_titulaire
            ):
                n_rem += 1
            else:
                n_tit += 1
            section = p.section_for_roster()
            if section is not None and section.pk in expected_ids:
                covered_section_ids.add(section.pk)

        maybe_by_section: dict[int, list[dict]] = defaultdict(list)
        maybe_entries: list[dict] = []
        for p in maybes:
            user = p.user
            name = user.get_full_name() or user.username
            entry = {
                "user_id": user.pk,
                "name": name,
                "poste": p.poste or "",
                "poste_label": p.poste_label if p.poste else "",
                "remind_at": p.maybe_remind_at,
                "remind_weekly": bool(p.maybe_remind_weekly),
            }
            maybe_entries.append(entry)
            section = p.section_for_roster()
            if section is not None:
                maybe_by_section[section.pk].append(entry)

        missing_sections = [s for s in expected if s.pk not in covered_section_ids]
        missing = [s.name for s in missing_sections]
        taken = by_event_taken.get(event.pk, set())
        missing_detail = []
        for section in missing_sections:
            eligible = [
                entry
                for entry in remplacants_idx.get(section.code, [])
                if entry["user_id"] not in taken
            ]
            missing_detail.append(
                {
                    "section_id": section.pk,
                    "code": section.code,
                    "name": section.name,
                    "eligible": eligible,
                    "maybe": maybe_by_section.get(section.pk, []),
                }
            )
        local_start = timezone.localtime(event.date_debut)
        venue = event.venue
        lieu = ""
        if venue is not None:
            lieu = f"{venue.nom} — {venue.ville}" if venue.ville else venue.nom

        is_concert = _is_concert_type(event)
        is_rehearsal = _is_rehearsal_type(event)
        statut = getattr(event, "statut", "") or ""
        is_proposal = (not is_rehearsal) and statut == Event.Statut.TENTATIVE
        is_confirmed = (not is_rehearsal) and statut == Event.Statut.CONFIRME
        if is_rehearsal:
            layer = "rehearsal"
            kind_label = "Répétition"
        elif is_proposal:
            layer = "proposal"
            kind_label = "Proposition"
        elif is_confirmed:
            layer = "confirmed"
            kind_label = "Confirmé"
        else:
            layer = "other"
            kind_label = getattr(getattr(event, "type", None), "nom", "") or "Événement"
        type_nom = getattr(getattr(event, "type", None), "nom", "") or ""
        proposed_by_label, deadline_label = _linked_proposal_meta(event)
        summaries[event.pk] = {
            "titre": event.titre,
            "is_concert": is_concert,
            "is_rehearsal": is_rehearsal,
            "is_proposal": is_proposal,
            "is_confirmed": is_confirmed,
            "statut": statut,
            "layer": layer,
            "kind_label": kind_label,
            "type_nom": type_nom,
            "date_label": local_start.strftime("%d/%m/%Y"),
            "time_label": local_start.strftime("%H:%M"),
            "lieu": lieu,
            "proposed_by_label": proposed_by_label,
            "deadline_label": deadline_label,
            "n_titulaires": n_tit,
            "n_remplacants": n_rem,
            "n_presents": n_tit + n_rem,
            "n_maybe": len(maybe_entries),
            "maybe_detail": maybe_entries,
            "instruments_manquants": missing,
            "instruments_manquants_label": (
                ", ".join(missing) if missing else "Aucun"
            ),
            "instruments_manquants_detail": missing_detail,
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
        from chat.services import unread_counts_for_memberships

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

    unread_counts = unread_counts_for_memberships(memberships)
    links: dict[int, dict] = {}
    for m in memberships:
        event_id = m.room.event_id
        if event_id is None:
            continue
        links[event_id] = {
            "room_id": m.room_id,
            "unread": unread_counts.get(m.pk, 0),
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


def attach_calendar_setlists(events) -> list:
    """Attache ``event.cal_setlist`` ({id, title} ou None) pour la setlist active."""
    events = list(events)
    for event in events:
        event.cal_setlist = None
    if not events:
        return events
    try:
        from django.db import OperationalError, ProgrammingError

        from repertoire.models import Setlist
    except ImportError:
        return events

    event_ids = [e.pk for e in events]
    try:
        rows = (
            Setlist.objects.filter(event_id__in=event_ids, is_active=True)
            .order_by("event_id", "-updated_at")
            .values("id", "title", "event_id")
        )
    except (ProgrammingError, OperationalError):
        return events

    by_event: dict[int, dict] = {}
    for row in rows:
        eid = row["event_id"]
        if eid not in by_event:
            by_event[eid] = {"id": row["id"], "title": row["title"]}
    for event in events:
        event.cal_setlist = by_event.get(event.pk)
    return events


def attach_calendar_roadmaps(events) -> list:
    """
    Attache ``event.cal_roadmap`` ({id} ou None) pour les feuilles de route validées.

    Validée = notification envoyée aux participants (``notified_at`` renseigné).
    """
    events = list(events)
    for event in events:
        event.cal_roadmap = None
    if not events:
        return events
    try:
        from django.db import OperationalError, ProgrammingError

        from planning.models import EventRoadmap
    except ImportError:
        return events

    event_ids = [e.pk for e in events]
    try:
        rows = (
            EventRoadmap.objects.filter(
                event_id__in=event_ids,
                notified_at__isnull=False,
            )
            .values("id", "event_id")
        )
    except (ProgrammingError, OperationalError):
        logger.warning("attach_calendar_roadmaps: schéma manquant")
        return events

    by_event = {row["event_id"]: {"id": row["id"]} for row in rows}
    for event in events:
        if getattr(event, "is_rehearsal", False):
            continue
        event.cal_roadmap = by_event.get(event.pk)
    return events


def chat_link_for_event(event, user) -> dict | None:
    """Salon + non lus pour un événement, ou None si pas d’accès."""
    return calendar_chat_links_for_user([event], user).get(event.pk)


