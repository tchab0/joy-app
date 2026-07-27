"""Feuille de route concert : préremplissage, suggestions, notification."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from django.db import OperationalError, ProgrammingError, transaction
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from planning.models import EventParticipation, EventRoadmap
from planning.services._notify import notify_users

logger = logging.getLogger(__name__)

DEFAULT_MATERIAL_NOTES = (
    "- Votre instrument\n"
    "- Vos partitions (et des pinces à linge)\n"
    "- Votre pupitre (blanc devant pour les sax, noir pour les autres)\n"
    "- Recommandé : bouteille d’eau / gourde ; rallonge ou multiprise "
    "pour les concernés"
)

DEFAULT_DRESS_CODE = "noir"

DEFAULT_CLOSING_NOTE = (
    "Un grand merci pour votre investissement et votre bonne humeur."
)

# Offsets par défaut avant le début du concert (minutes).
DEFAULT_ARRIVAL_START_OFFSET = 75
DEFAULT_ARRIVAL_END_OFFSET = 60
DEFAULT_SOUNDCHECK_OFFSET = 45


def maps_url_for_event(event: Event) -> str:
    """Lien carte depuis coordonnées du lieu, sinon recherche adresse."""
    venue = getattr(event, "venue", None)
    if venue is None:
        return ""
    if venue.has_coords:
        return (
            f"https://www.google.com/maps/search/?api=1"
            f"&query={venue.latitude},{venue.longitude}"
        )
    parts = [p for p in (venue.nom, venue.adresse, venue.ville) if p]
    if not parts:
        return ""
    from urllib.parse import quote_plus

    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(', '.join(parts))}"


def concert_end_note_for_event(event: Event) -> str:
    """Libellé fin de concert depuis date_fin, sinon vide."""
    if not event.date_fin:
        return ""
    fin = timezone.localtime(event.date_fin)
    return fin.strftime("%Hh%M").replace("h00", "h")


def _local_concert_start(event: Event) -> datetime:
    return timezone.localtime(event.date_debut)


def _time_minus(start: datetime, minutes: int) -> time:
    return (start - timedelta(minutes=minutes)).time().replace(second=0, microsecond=0)


def _offset_minutes(concert: datetime, value: time | None) -> int | None:
    if value is None:
        return None
    concert_t = concert.time().replace(second=0, microsecond=0)
    c_min = concert_t.hour * 60 + concert_t.minute
    v_min = value.hour * 60 + value.minute
    return c_min - v_min


def previous_roadmap_for_venue(event: Event) -> EventRoadmap | None:
    """Dernière feuille de route au même lieu (hors événement courant)."""
    venue_id = getattr(event, "venue_id", None)
    if not venue_id:
        return None
    try:
        return (
            EventRoadmap.objects.filter(event__venue_id=venue_id)
            .exclude(event_id=event.pk)
            .select_related("event")
            .order_by("-event__date_debut")
            .first()
        )
    except (ProgrammingError, OperationalError):
        logger.warning("previous_roadmap_for_venue: schéma manquant")
        return None


def previous_roadmap_global(event: Event) -> EventRoadmap | None:
    """Dernière feuille de route quelconque (hors événement courant)."""
    try:
        return (
            EventRoadmap.objects.exclude(event_id=event.pk)
            .select_related("event")
            .order_by("-event__date_debut")
            .first()
        )
    except (ProgrammingError, OperationalError):
        logger.warning("previous_roadmap_global: schéma manquant")
        return None


def suggest_defaults(event: Event) -> dict[str, Any]:
    """
    Valeurs proposées pour une nouvelle feuille / champs vides.

    Priorité : même lieu → dernière feuille globale → constantes PDF.
    """
    start = _local_concert_start(event)
    same_venue = previous_roadmap_for_venue(event)
    any_prev = same_venue or previous_roadmap_global(event)

    arrival_start_off = DEFAULT_ARRIVAL_START_OFFSET
    arrival_end_off = DEFAULT_ARRIVAL_END_OFFSET
    soundcheck_off = DEFAULT_SOUNDCHECK_OFFSET
    ready_off = 0

    if same_venue and same_venue.event_id:
        prev_start = _local_concert_start(same_venue.event)
        for attr, fallback_name in (
            ("arrival_start", "arrival_start_off"),
            ("arrival_end", "arrival_end_off"),
            ("soundcheck_at", "soundcheck_off"),
            ("ready_at", "ready_off"),
        ):
            off = _offset_minutes(prev_start, getattr(same_venue, attr))
            if off is not None:
                if fallback_name == "arrival_start_off":
                    arrival_start_off = off
                elif fallback_name == "arrival_end_off":
                    arrival_end_off = off
                elif fallback_name == "soundcheck_off":
                    soundcheck_off = off
                else:
                    ready_off = off

    parking = ""
    if same_venue and same_venue.parking_info.strip():
        parking = same_venue.parking_info.strip()
    elif any_prev and any_prev.parking_info.strip() and same_venue is None:
        # Pas de même lieu : on propose quand même en hint, pas en valeur forcée.
        parking = ""

    material = DEFAULT_MATERIAL_NOTES
    if any_prev and any_prev.material_notes.strip():
        material = any_prev.material_notes.strip()

    dress = DEFAULT_DRESS_CODE
    if any_prev and any_prev.dress_code.strip():
        dress = any_prev.dress_code.strip()

    closing = DEFAULT_CLOSING_NOTE
    if any_prev and any_prev.closing_note.strip():
        closing = any_prev.closing_note.strip()

    return {
        "maps_url": maps_url_for_event(event),
        "venue_extra": (same_venue.venue_extra.strip() if same_venue else ""),
        "concert_end_note": concert_end_note_for_event(event),
        "arrival_start": _time_minus(start, arrival_start_off),
        "arrival_end": _time_minus(start, arrival_end_off),
        "soundcheck_at": _time_minus(start, soundcheck_off),
        "ready_at": _time_minus(start, ready_off) if ready_off else start.time().replace(
            second=0, microsecond=0
        ),
        "parking_info": parking,
        "material_notes": material,
        "dress_code": dress,
        "closing_note": closing,
        "source_same_venue": same_venue,
        "source_any": any_prev,
        "parking_hint": (
            (any_prev.parking_info.strip() if any_prev else "")
            if not parking
            else ""
        ),
    }


def get_roadmap(event: Event) -> EventRoadmap | None:
    try:
        return EventRoadmap.objects.select_related(
            "event", "event__venue", "event__type", "updated_by"
        ).get(event=event)
    except EventRoadmap.DoesNotExist:
        return None
    except (ProgrammingError, OperationalError):
        logger.warning("get_roadmap: schéma manquant event_id=%s", event.pk)
        return None


@transaction.atomic
def get_or_create_roadmap(event: Event, *, user=None) -> EventRoadmap:
    """Crée la feuille préremplie si absente ; ne touche pas une existante."""
    existing = get_roadmap(event)
    if existing is not None:
        return existing

    defaults = suggest_defaults(event)
    roadmap = EventRoadmap(
        event=event,
        maps_url=defaults["maps_url"],
        venue_extra=defaults["venue_extra"],
        concert_end_note=defaults["concert_end_note"],
        arrival_start=defaults["arrival_start"],
        arrival_end=defaults["arrival_end"],
        soundcheck_at=defaults["soundcheck_at"],
        ready_at=defaults["ready_at"],
        parking_info=defaults["parking_info"],
        material_notes=defaults["material_notes"],
        dress_code=defaults["dress_code"],
        closing_note=defaults["closing_note"],
        updated_by=user if getattr(user, "is_authenticated", False) else None,
    )
    roadmap.save()
    return roadmap


def sync_known_fields(roadmap: EventRoadmap) -> list[str]:
    """
    Met à jour les champs encore vides avec des données désormais connues
    (lieu → maps, date_fin → fin approx.). Retourne les champs synchronisés.
    """
    changed: list[str] = []
    event = roadmap.event
    if not roadmap.maps_url:
        url = maps_url_for_event(event)
        if url:
            roadmap.maps_url = url
            changed.append("maps_url")
    if not roadmap.concert_end_note:
        note = concert_end_note_for_event(event)
        if note:
            roadmap.concert_end_note = note
            changed.append("concert_end_note")
    if changed:
        roadmap.save(update_fields=[*changed, "updated_at"])
    return changed


def apply_suggestion(roadmap: EventRoadmap, field: str) -> bool:
    """Applique la suggestion pour un champ vide. Retourne True si modifié."""
    if field not in {
        "maps_url",
        "venue_extra",
        "concert_end_note",
        "arrival_start",
        "arrival_end",
        "soundcheck_at",
        "ready_at",
        "parking_info",
        "material_notes",
        "dress_code",
        "closing_note",
    }:
        return False
    current = getattr(roadmap, field)
    if isinstance(current, str) and current.strip():
        return False
    if current is not None and not isinstance(current, str):
        return False
    defaults = suggest_defaults(roadmap.event)
    value = defaults.get(field)
    if field == "parking_info" and not value:
        value = defaults.get("parking_hint") or ""
    if value in (None, ""):
        return False
    setattr(roadmap, field, value)
    roadmap.save(update_fields=[field, "updated_at"])
    return True


def roadmap_recipients(event: Event):
    """Participants à notifier (hors refus)."""
    return (
        EventParticipation.objects.filter(event=event)
        .exclude(status__code="declined")
        .select_related("user")
    )


def notify_roadmap(event: Event, *, actor=None) -> int:
    """Envoie une notification avec lien direct vers la feuille de route."""
    roadmap = get_roadmap(event)
    if roadmap is None:
        return 0

    path = reverse("planning:event_roadmap", kwargs={"pk": event.pk})
    when = timezone.localtime(event.date_debut).strftime("%d/%m/%Y")
    body = (
        f"Feuille de route disponible pour « {event.titre} » ({when}). "
        f"Horaires, lieu, matériel et consignes."
    )
    users = [p.user for p in roadmap_recipients(event)]
    sent = notify_users(
        users,
        title="JOY — Feuille de route",
        body=body,
        url=path,
        related_type="event_roadmap",
        related_id=event.pk,
    )
    now = timezone.now()
    EventRoadmap.objects.filter(pk=roadmap.pk).update(notified_at=now)
    roadmap.notified_at = now
    return sent


def user_can_view_roadmap(user, event: Event, participation=None) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    if participation is not None:
        return True
    return EventParticipation.objects.filter(event=event, user=user).exists()
