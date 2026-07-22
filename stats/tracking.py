from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import OperationalError, ProgrammingError

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Préfixes privés → nom d’événement (premier match gagne).
PATH_EVENT_RULES: tuple[tuple[str, str], ...] = (
    ("/planning/moi/", "planning.moi"),
    ("/planning/polls/", "planning.polls"),
    ("/planning/admin/", "planning.admin"),
    ("/planning/proposer/", "planning.propose"),
    ("/planning/", "planning.view"),
    ("/chat/", "chat.view"),
    ("/repertoire/staff/", "repertoire.staff"),
    ("/repertoire/", "repertoire.view"),
    ("/compte/", "compte.view"),
    ("/feedback/", "feedback.view"),
)

SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/stats/",
    "/admin/",
    "/sw.js",
    "/manifest.webmanifest",
)

# Téléchargements loggés explicitement dans les vues (évite le double hit).
SKIP_EXACT_OR_PREFIX = (
    "/repertoire/partition/",
)


def feature_name_for_path(path: str) -> str | None:
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return None
    if any(path.startswith(p) for p in SKIP_EXACT_OR_PREFIX):
        return None
    # Audio : /repertoire/morceau/<slug>/audio/
    if path.startswith("/repertoire/morceau/") and path.rstrip("/").endswith("/audio"):
        return None
    for prefix, name in PATH_EVENT_RULES:
        if path.startswith(prefix):
            return name
    return None


def record_usage(
    *,
    name: str,
    user=None,
    path: str = "",
) -> None:
    """Enregistre un UsageEvent ; ignore si le schéma n’est pas encore migré."""
    try:
        from stats.models import UsageEvent

        UsageEvent.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None,
            name=name[:64],
            path=(path or "")[:300],
        )
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("UsageEvent ignoré (%s): %s", name, exc)
    except Exception:
        logger.exception("Échec enregistrement UsageEvent (%s)", name)


def record_request_usage(request: HttpRequest) -> None:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return
    if request.method not in ("GET", "HEAD"):
        return
    path = request.path or ""
    name = feature_name_for_path(path)
    if not name:
        return
    record_usage(name=name, user=user, path=path)
