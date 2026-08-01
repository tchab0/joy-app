"""Lien entre events.Event (planning) et EvenementMedia (galerie)."""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from core.models import EvenementMedia


def ensure_evenement_media_for_event(event) -> EvenementMedia:
    """
    Retrouve ou crée l’EvenementMedia correspondant à un Event planning.

    Appariement : même nom + même date locale ; sinon création.
    """
    local_day = timezone.localtime(event.date_debut).date()
    existing = (
        EvenementMedia.objects.filter(nom=event.titre, date=local_day)
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


def media_submit_url_for_event(event) -> str:
    """URL relative pour proposer photos/vidéos, événement prérempli."""
    return f"{reverse('proposer_media')}?event={event.pk}"
