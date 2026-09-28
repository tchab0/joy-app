"""Lien entre events.Event (planning) et EvenementMedia (galerie)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import EvenementMedia


def find_evenement_media_for_event(event) -> EvenementMedia | None:
    """
    Retrouve l’EvenementMedia d’un Event, sans le créer.

    Appariement : même nom + même date locale ; sinon même date avec un nom
    qui commence par le titre du concert.
    """
    local_day = timezone.localtime(event.date_debut).date()
    existing = (
        EvenementMedia.objects.filter(nom=event.titre, date=local_day)
        .order_by("pk")
        .first()
    )
    if existing is None:
        existing = (
            EvenementMedia.objects.filter(
                date=local_day, nom__istartswith=event.titre
            )
            .order_by("pk")
            .first()
        )
    return existing


def ensure_evenement_media_for_event(event) -> EvenementMedia:
    """Retrouve ou crée l’EvenementMedia correspondant à un Event planning."""
    existing = find_evenement_media_for_event(event)
    if existing:
        return existing
    local_day = timezone.localtime(event.date_debut).date()
    lieu = ""
    venue = getattr(event, "venue", None)
    if venue is not None:
        lieu = f"{venue.nom} — {venue.ville}" if venue.ville else (venue.nom or "")
    return EvenementMedia.objects.create(nom=event.titre, date=local_day, lieu=lieu)


def _concerts_started_through_today():
    """Concerts confirmés dont le jour de début local est ≤ aujourd’hui (plus récent d’abord)."""
    from events.models import Event

    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    # Fin exclusive de la journée locale : inclut tout concert commencé aujourd’hui.
    end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min), tz)
    return (
        Event.objects.filter(
            statut=Event.Statut.CONFIRME,
            type__nom__icontains="concert",
            date_debut__lt=end,
        )
        .exclude(type__is_rehearsal=True)
        .select_related("venue", "type")
        .order_by("-date_debut", "-pk")
    )


def default_concert_media_event():
    """
    Dernier concert déjà commencé : crée l’EvenementMedia si besoin et le
    retourne comme défaut jusqu’au prochain concert (jour de début inclus).

    Retourne (Event, EvenementMedia) ou (None, None).
    """
    event = _concerts_started_through_today().first()
    if event is None:
        return None, None
    return event, ensure_evenement_media_for_event(event)


def published_media_for_past_event(event) -> dict | None:
    """
    Médias publiés rattachés à un concert déjà commencé.

    Retourne None pour un concert à venir, ou s’il n’a aucun média publié.
    """
    from core.models import MediaItem

    if event.date_debut >= timezone.now():
        return None
    evenement = find_evenement_media_for_event(event)
    if evenement is None:
        return None
    items = list(
        MediaItem.objects.filter(evenement=evenement, publie=True).order_by(
            "ordre", "id"
        )
    )
    groups = {"photos": [], "videos": [], "audios": [], "pdfs": []}
    buckets = {
        "photo": groups["photos"],
        "video": groups["videos"],
        "audio": groups["audios"],
        "pdf": groups["pdfs"],
    }
    for item in items:
        bucket = buckets.get(item.type)
        if bucket is None:
            continue
        item.display_url = item.url_affichage
        item.thumb_url = item.url_miniature
        bucket.append(item)
    if not any(groups.values()):
        return None
    groups["evenement"] = evenement
    return groups


def media_submit_url_for_event(event) -> str:
    """URL relative pour proposer photos/vidéos, événement prérempli."""
    return f"{reverse('proposer_media')}?event={event.pk}"
