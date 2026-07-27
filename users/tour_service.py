"""Sérialisation et logique des guides (coach marks)."""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import cache
from django.db import OperationalError, ProgrammingError
from django.middleware.csrf import get_token
from django.urls import reverse

from users.roles import user_can_access_planning

logger = logging.getLogger(__name__)
TOUR_CACHE_VERSION_KEY = "users:product-tour-version"
TOUR_CACHE_TTL = 24 * 60 * 60


def product_tour_cache_version() -> int:
    cache.add(TOUR_CACHE_VERSION_KEY, 1, None)
    return int(cache.get(TOUR_CACHE_VERSION_KEY, 1))


def _safe_tours_payload() -> list[dict[str, Any]]:
    """Tolère l’absence de tables (migration pas encore appliquée)."""
    from users.tour_models import ProductTour

    cache_key = f"users:product-tours:v{product_tour_cache_version()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        tours = list(
            serialize_tour(tour)
            for tour in ProductTour.objects.filter(is_active=True)
            .prefetch_related("steps")
            .order_by("audience")
        )
        cache.set(cache_key, tours, TOUR_CACHE_TTL)
        return tours
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Guides coach marks indisponibles (schéma) : %s", exc)
        return []


def user_tour_completed_version(user, audience: str) -> int:
    if audience == "musician":
        return int(getattr(user, "tour_musician_version", 0) or 0)
    if audience == "staff":
        return int(getattr(user, "tour_staff_version", 0) or 0)
    return 0


def user_can_take_tour(user, audience: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if audience == "musician":
        return user_can_access_planning(user)
    if audience == "staff":
        return bool(user.is_staff or user.is_superuser)
    return False


def serialize_tour(tour) -> dict[str, Any]:
    steps = [
        {
            "order": step.order,
            "anchor": step.anchor,
            "title": step.title,
            "body": step.body,
            "page_path": step.page_path,
            "open_mobile_nav": step.open_mobile_nav,
            "scroll_footer": step.scroll_footer,
        }
        for step in tour.steps.all()
        if step.is_active
    ]
    steps.sort(key=lambda s: (s["order"],))
    return {
        "audience": tour.audience,
        "title": tour.title,
        "version": tour.version,
        "steps": steps,
    }


def build_tour_config(request) -> dict[str, Any] | None:
    """Config JSON pour le JS — None si anonyme ou rien à faire / disponible."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    tours = _safe_tours_payload()
    if not tours:
        return None

    by_audience: dict[str, Any] = {}
    pending: list[str] = []
    for tour in tours:
        audience = tour["audience"]
        if not user_can_take_tour(user, audience):
            continue
        if not tour["steps"]:
            continue
        by_audience[audience] = tour
        done_v = user_tour_completed_version(user, audience)
        if done_v < tour["version"]:
            pending.append(audience)

    # Ordre : musicien puis staff
    pending.sort(key=lambda a: 0 if a == "musician" else 1)

    force = (request.GET.get("tour") or "").strip().lower()
    if force not in by_audience:
        force = ""

    # Replay : boutons visibles même si déjà terminé
    can_replay = {
        "musician": "musician" in by_audience,
        "staff": "staff" in by_audience,
    }

    if not by_audience:
        return None

    return {
        "pending": pending,
        "force": force or None,
        "tours": by_audience,
        "can_replay": can_replay,
        "complete_url": reverse("account_tour_complete"),
        "csrf_token": get_token(request),
    }


def mark_tour_complete(user, audience: str, version: int) -> bool:
    """Enregistre la version terminée. Retourne False si audience invalide."""
    if not user_can_take_tour(user, audience):
        return False
    version = max(0, int(version))
    if audience == "musician":
        user.tour_musician_version = version
        user.save(update_fields=["tour_musician_version"])
        return True
    if audience == "staff":
        user.tour_staff_version = version
        user.save(update_fields=["tour_staff_version"])
        return True
    return False
