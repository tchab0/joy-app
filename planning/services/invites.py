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
from planning.services.musicians import get_or_create_profile
from planning.services.status import get_status

def titulaires_queryset():
    """Musiciens actifs ayant un poste titulaire renseigné."""
    return User.objects.filter(
        is_musician=True,
        is_active=True,
        musician_profile__poste_titulaire__gt="",
    ).select_related("musician_profile")


def resolve_invite_slot(musician, poste: str) -> tuple[str, str]:
    """
    Valide le poste convoqué pour un musicien.

    Retourne (poste, role_kind). Lève ValueError si incohérent.
    Sans poste explicite : poste titulaire s’il existe, sinon l’unique slot.
    """
    poste = (poste or "").strip()
    try:
        profile = musician.musician_profile
    except MusicianProfile.DoesNotExist as exc:
        raise ValueError("Profil musicien manquant") from exc

    slots = invite_slots_for_profile(profile)
    if not slots:
        if not poste:
            return "", ""
        raise ValueError("Ce musicien n’a aucun poste renseigné")

    if not poste:
        # Défaut : titulaire, sinon unique chaise de remplacement.
        if profile.poste_titulaire:
            return (
                profile.poste_titulaire,
                EventParticipation.RoleKind.TITULAIRE,
            )
        if len(slots) == 1:
            return slots[0]["poste"], slots[0]["role_kind"]
        raise ValueError("Choisissez le poste pour lequel convoquer ce musicien")

    for slot in slots:
        if slot["poste"] == poste:
            return slot["poste"], slot["role_kind"]

    raise ValueError("Poste non associé à ce musicien")


def invite_slots_for_profile(profile: MusicianProfile) -> list[dict]:
    """Slots d’invitation (titulaire d’abord, puis remplaçants)."""
    slots: list[dict] = []
    if profile.poste_titulaire:
        slots.append(
            {
                "poste": profile.poste_titulaire,
                "role_kind": EventParticipation.RoleKind.TITULAIRE,
                "label": f"{profile.get_poste_titulaire_display()} (tit.)",
                "is_default": True,
            }
        )
    for poste in profile.postes_remplacant:
        slots.append(
            {
                "poste": poste,
                "role_kind": EventParticipation.RoleKind.REMPLACANT,
                "label": f"{profile.get_poste_remplacant_label(poste)} (remp.)",
                "is_default": False,
            }
        )
    if slots and not any(s["is_default"] for s in slots):
        slots[0]["is_default"] = True
    return slots


def invite_choices_for_musicians(musicians) -> list[dict]:
    """
    Options d’invitation aplaties : une entrée par (musicien, poste).

    value = « {user_id}:{poste} » pour le select HTML.
    Conservé pour compat ; préférer invite_musicians_for_form.
    """
    choices: list[dict] = []
    for entry in invite_musicians_for_form(musicians):
        if not entry["slots"]:
            choices.append(
                {
                    "value": f"{entry['user_id']}:",
                    "user_id": entry["user_id"],
                    "poste": "",
                    "label": entry["name"],
                }
            )
            continue
        for slot in entry["slots"]:
            choices.append(
                {
                    "value": f"{entry['user_id']}:{slot['poste']}",
                    "user_id": entry["user_id"],
                    "poste": slot["poste"],
                    "label": f"{entry['name']} · {slot['label']}",
                }
            )
    return choices


def invite_musicians_for_form(musicians) -> list[dict]:
    """
    Musiciens pour le formulaire d’invitation (titulaire par défaut).

    Chaque entrée : user_id, name, default_poste, slots[].
    """
    entries: list[dict] = []
    for m in musicians:
        name = m.get_full_name() or m.username
        try:
            profile = m.musician_profile
        except MusicianProfile.DoesNotExist:
            entries.append(
                {
                    "user_id": m.pk,
                    "name": name,
                    "default_poste": "",
                    "slots": [],
                }
            )
            continue
        slots = invite_slots_for_profile(profile)
        default = next((s["poste"] for s in slots if s.get("is_default")), "")
        if not default and slots:
            default = slots[0]["poste"]
        entries.append(
            {
                "user_id": m.pk,
                "name": name,
                "default_poste": default,
                "slots": [
                    {
                        "poste": s["poste"],
                        "label": s["label"],
                        "role_kind": s["role_kind"],
                        "is_default": bool(s.get("is_default")),
                    }
                    for s in slots
                ],
            }
        )
    return entries


def parse_invite_choice(raw: str) -> tuple[int | None, str]:
    """Parse « user_id:poste » depuis le formulaire d’invitation."""
    raw = (raw or "").strip()
    if not raw:
        return None, ""
    if ":" not in raw:
        try:
            return int(raw), ""
        except ValueError:
            return None, ""
    user_part, poste = raw.split(":", 1)
    try:
        return int(user_part), poste.strip()
    except ValueError:
        return None, ""


def invite_titulaires_to_event(event, *, send_notification: bool = False) -> int:
    """Convoque tous les titulaires à une date (ignore les déjà inscrits)."""
    invited = get_status("invited")
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
                status=invited,
                poste=poste,
                role_kind=EventParticipation.RoleKind.TITULAIRE,
            )
        )
    if to_create:
        EventParticipation.objects.bulk_create(to_create, ignore_conflicts=True)
        # bulk_create ne déclenche pas post_save → sync chat manuelle
        from chat.services import sync_participation_to_chat

        created_parts = list(
            EventParticipation.objects.filter(
                event=event, user_id__in=[p.user_id for p in to_create]
            ).select_related("user")
        )
        for part in created_parts:
            sync_participation_to_chat(part)
        if send_notification:
            notify_event_invite(event, [p.user for p in created_parts])
    return len(to_create)


def notify_event_invite(event, users) -> int:
    """Notification d’invitation au salon / événement."""
    users = list(users)
    if not users:
        return 0
    local = timezone.localtime(event.date_debut)
    date_label = local.strftime("%d/%m/%Y %H:%M")
    body = (
        f"Invitation : « {event.titre} » ({date_label}). "
        f"Ouvrez le salon de discussion pour répondre."
    )
    return notify_users(
        users,
        title="JOY — Invitation",
        body=body,
        url="/chat/",
        requires_response=True,
        related_type="event",
        related_id=event.pk,
    )


def send_event_photos_requests(events, members) -> int:
    """
    Demande photos/vidéos aux membres pour chaque événement (J+7).

    Marque ``photos_request_sent_at`` même si 0 notif (évite de spammer au prochain run).
    Retourne le total de notifications envoyées.
    """
    from core.media_events import media_submit_url_for_event

    events = list(events)
    members = list(members)
    if not events:
        return 0

    total = 0
    now = timezone.now()
    for event in events:
        day = timezone.localtime(event.date_debut)
        title = f"Photos — {event.titre}"
        body = (
            f"Une semaine après « {event.titre} » "
            f"({day.strftime('%d/%m/%Y')}), "
            f"partagez vos photos et vidéos du jour !"
        )
        url = media_submit_url_for_event(event)
        if members:
            total += notify_users(members, title=title, body=body, url=url)
        Event.objects.filter(pk=event.pk).update(photos_request_sent_at=now)
        event.photos_request_sent_at = now
    return total


@transaction.atomic
def invite_musician_to_event(
    event,
    musician,
    *,
    poste: str = "",
    send_notification: bool = True,
) -> tuple[EventParticipation, bool]:
    """
    Invite un musicien individuellement (roster + salon) + notification optionnelle.

    ``poste`` est obligatoire si le musicien a plusieurs postes.
    Retourne (participation, created).
    """
    if not getattr(musician, "is_musician", False) or not musician.is_active:
        raise ValueError("Utilisateur non musicien ou inactif")
    poste, role_kind = resolve_invite_slot(musician, poste)
    invited = get_status("invited")
    try:
        part, created = EventParticipation.objects.get_or_create(
            event=event,
            user=musician,
            defaults={
                "status": invited,
                "poste": poste,
                "role_kind": role_kind,
            },
        )
    except IntegrityError:
        part = EventParticipation.objects.select_related("status").get(
            event=event, user=musician
        )
        created = False

    reinvite = False
    if not created:
        updates = ["updated_at"]
        if part.status_id != invited.pk:
            part.status = invited
            updates.append("status")
            reinvite = True
        if poste and part.poste != poste:
            part.poste = poste
            updates.append("poste")
            reinvite = True
        if part.role_kind != role_kind:
            part.role_kind = role_kind
            updates.append("role_kind")
            reinvite = True
        if reinvite or "poste" in updates or "role_kind" in updates:
            part.save(update_fields=updates)

    from chat.services import sync_participation_to_chat

    sync_participation_to_chat(part)
    if (created or reinvite) and send_notification:
        notify_event_invite(event, [musician])
    return part, created


@transaction.atomic
def propose_event(
    *,
    proposer,
    titre: str,
    event_type,
    venue,
    date_debut,
    date_fin=None,
    description: str = "",
    organisme: str = "",
    parent=None,
    public: bool = False,
    contact_nom: str = "",
    contact_telephone: str = "",
    contact_email: str = "",
    deadline=None,
):
    """
    Proposition d’événement par un musicien / adhérent / staff.

    Crée l’Event (tentative), un sondage brouillon lié, et laisse le signal
    chat créer un salon staff-only (pas de convocation auto des titulaires).
    """
    from events.models import Event

    titre = (titre or "").strip()
    if not titre:
        raise ValueError("Titre requis")

    event = Event(
        titre=titre,
        type=event_type,
        venue=venue,
        date_debut=date_debut,
        date_fin=date_fin,
        description=(description or "").strip(),
        statut=Event.Statut.TENTATIVE,
        public=public,
        parent=parent,
        organisme=(organisme or "").strip(),
        contact_nom=(contact_nom or "").strip(),
        contact_telephone=(contact_telephone or "").strip(),
        contact_email=(contact_email or "").strip(),
        proposed_by=proposer,
    )
    # Pas de convocation auto : le staff invite individuellement.
    event._skip_titulaire_invite = True
    event.save()

    proposal = DateProposal.objects.create(
        title=titre,
        description=(description or "").strip(),
        status=DateProposal.Status.DRAFT,
        created_by=proposer,
        linked_event=event,
        deadline=deadline,
    )
    DateOption.objects.create(
        proposal=proposal,
        starts_at=date_debut,
        ends_at=date_fin,
        label="",
        sort_order=0,
    )
    return event, proposal


