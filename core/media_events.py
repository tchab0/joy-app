"""Lien entre events.Event (planning) et EvenementMedia (galerie)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import EvenementMedia


def ensure_evenement_media_for_event(event) -> EvenementMedia:
    """
    Retrouve ou crée l’EvenementMedia correspondant à un Event planning.

    Appariement : même nom + même date locale ; sinon même date avec un nom
    qui commence par le titre du concert ; sinon création.
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
    if existing:
        return existing
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


def media_submit_url_for_event(event) -> str:
    """URL relative pour proposer photos/vidéos, événement prérempli."""
    return f"{reverse('proposer_media')}?event={event.pk}"
