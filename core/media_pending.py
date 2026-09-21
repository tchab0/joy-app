"""File de modération des médias soumis (badge menu staff)."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)

PENDING_MEDIA_CACHE_KEY = "core:pending-media-count"
PENDING_MEDIA_CACHE_TTL = 60
# En attente de décision, ou compression encore en cours (pas encore publié / refusé).
PENDING_MEDIA_STATUTS = ("en_attente", "en_cours")


def pending_media_count() -> int:
    """Nombre de médias pas encore publiés ni refusés. 0 si le schéma n'est pas prêt."""
    cached = cache.get(PENDING_MEDIA_CACHE_KEY)
    if cached is not None:
        return int(cached)
    try:
        from core.models import MediaItem

        count = MediaItem.objects.filter(statut__in=PENDING_MEDIA_STATUTS).count()
    except (ProgrammingError, OperationalError):
        logger.warning("pending_media_count indisponible (migration ?)")
        return 0
    cache.set(PENDING_MEDIA_CACHE_KEY, count, PENDING_MEDIA_CACHE_TTL)
    return count


def invalidate_pending_media_count() -> None:
    cache.delete(PENDING_MEDIA_CACHE_KEY)
