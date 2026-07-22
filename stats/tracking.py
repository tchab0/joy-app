from __future__ import annotations

import logging
import re
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
    "/robots.txt",
    "/sitemap.xml",
    "/favicon",
)

# Téléchargements loggés explicitement dans les vues (évite le double hit).
SKIP_EXACT_OR_PREFIX = (
    "/repertoire/partition/",
)

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|wget|curl|python-requests|"
    r"httpclient|monitoring|uptime|headless",
    re.I,
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


def _is_bot(request: HttpRequest) -> bool:
    ua = request.META.get("HTTP_USER_AGENT") or ""
    if not ua.strip():
        return True
    return bool(_BOT_RE.search(ua))


def _is_trackable_html(request: HttpRequest, response) -> bool:
    if request.method != "GET":
        return False
    ctype = (response.get("Content-Type") or "").lower()
    if ctype and "text/html" not in ctype:
        return False
    return True


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


def record_public_pageview(request: HttpRequest) -> None:
    """Enregistre une vue de page publique (session anonyme, pas d’IP)."""
    from core.seo import path_should_noindex

    path = request.path or "/"
    if path_should_noindex(path):
        return
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return
    if _is_bot(request):
        return

    try:
        # Crée une session si besoin pour compter les visiteurs uniques.
        if not request.session.session_key:
            request.session.save()
        session_key = request.session.session_key or ""
        from stats.models import PublicPageView

        PublicPageView.objects.create(
            path=path[:300],
            session_key=session_key[:40],
        )
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("PublicPageView ignoré (%s): %s", path, exc)
    except Exception:
        logger.exception("Échec enregistrement PublicPageView (%s)", path)


def record_request_usage(request: HttpRequest, response=None) -> None:
    if response is not None and not _is_trackable_html(request, response):
        return
    if request.method not in ("GET", "HEAD"):
        return

    user = getattr(request, "user", None)
    path = request.path or ""

    # Audience publique (y compris staff/musiciens qui consultent le site public).
    from core.seo import path_should_noindex

    if not path_should_noindex(path):
        if response is None or _is_trackable_html(request, response):
            if request.method == "GET" and not _is_bot(request):
                record_public_pageview(request)
        return

    # Outils authentifiés uniquement.
    if not user or not user.is_authenticated:
        return
    name = feature_name_for_path(path)
    if not name:
        return
    record_usage(name=name, user=user, path=path)
