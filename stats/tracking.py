from __future__ import annotations

import logging
import re
import secrets
import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.core import signing
from django.utils import timezone

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Mise à jour last_seen_at au plus une fois par heure (évite un UPDATE par hit).
LAST_SEEN_SESSION_KEY = "_joy_last_seen_touch"
LAST_SEEN_THROTTLE_SECONDS = 3600

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


def touch_last_seen(*, request: HttpRequest | None = None, user=None, force: bool = False) -> None:
    """Met à jour User.last_seen_at (activité réelle, pas seulement le login formulaire)."""
    if user is None and request is not None:
        user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return
    if getattr(user, "is_anonymous", False):
        return

    now_ts = time.time()
    if not force and request is not None and hasattr(request, "session"):
        try:
            prev = float(request.session.get(LAST_SEEN_SESSION_KEY) or 0)
        except (TypeError, ValueError):
            prev = 0.0
        if prev and (now_ts - prev) < LAST_SEEN_THROTTLE_SECONDS:
            return

    now = timezone.now()
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    qs = User.objects.filter(pk=user.pk)
    if not force:
        cutoff = now - timedelta(seconds=LAST_SEEN_THROTTLE_SECONDS)
        qs = qs.filter(Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=cutoff))
    try:
        updated = qs.update(last_seen_at=now)
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("last_seen_at ignoré: %s", exc)
        return

    if updated:
        try:
            user.last_seen_at = now
        except Exception:
            pass
    if request is not None and hasattr(request, "session"):
        try:
            request.session[LAST_SEEN_SESSION_KEY] = str(now_ts)
        except Exception:
            pass


def record_usage(
    *,
    name: str,
    user=None,
    path: str = "",
    request: HttpRequest | None = None,
) -> None:
    """Enregistre un UsageEvent ; ignore si le schéma n’est pas encore migré."""
    try:
        from stats.models import UsageEvent

        auth_user = user if getattr(user, "is_authenticated", False) else None
        UsageEvent.objects.create(
            user=auth_user,
            name=name[:64],
            path=(path or "")[:300],
        )
        if auth_user is not None:
            touch_last_seen(request=request, user=auth_user)
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("UsageEvent ignoré (%s): %s", name, exc)
    except Exception:
        logger.exception("Échec enregistrement UsageEvent (%s)", name)


PUBLIC_VISITOR_COOKIE = "joy_visitor"
PUBLIC_VISITOR_COOKIE_SALT = "stats.public-visitor"
PUBLIC_VISITOR_COOKIE_AGE = 365 * 24 * 60 * 60


def _public_visitor_id(request: HttpRequest, response) -> str:
    """Retourne un identifiant visiteur signé sans créer de session Django."""
    raw_cookie = request.COOKIES.get(PUBLIC_VISITOR_COOKIE, "")
    try:
        payload = signing.loads(
            raw_cookie,
            salt=PUBLIC_VISITOR_COOKIE_SALT,
            max_age=PUBLIC_VISITOR_COOKIE_AGE,
        )
        visitor_id = str(payload.get("id", "")) if isinstance(payload, dict) else ""
        if visitor_id:
            return visitor_id
    except (signing.BadSignature, TypeError, ValueError):
        pass

    visitor_id = secrets.token_urlsafe(18)
    response.set_cookie(
        PUBLIC_VISITOR_COOKIE,
        signing.dumps({"id": visitor_id}, salt=PUBLIC_VISITOR_COOKIE_SALT),
        max_age=PUBLIC_VISITOR_COOKIE_AGE,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
    )
    return visitor_id


def record_public_pageview(request: HttpRequest, response) -> None:
    """Enregistre une vue de page publique (cookie signé, pas d’IP)."""
    from core.seo import path_should_noindex

    path = request.path or "/"
    if path_should_noindex(path):
        return
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return
    if _is_bot(request):
        return

    try:
        visitor_id = _public_visitor_id(request, response)
        # Échantillonner 1 INSERT sur 5 (cookie visiteur déjà posé).
        if secrets.randbelow(5) != 0:
            return
        from stats.models import PublicPageView

        PublicPageView.objects.create(
            path=path[:300],
            session_key=visitor_id[:40],
        )
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("PublicPageView ignoré (%s): %s", path, exc)
    except Exception:
        logger.exception("Échec enregistrement PublicPageView (%s)", path)


def record_request_usage(request: HttpRequest, response=None) -> None:
    if response is not None and not _is_trackable_html(request, response):
        return
    if response is not None and response.get("X-JOY-Page-Cache") == "HIT":
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
                record_public_pageview(request, response)
        return

    # Outils authentifiés uniquement.
    if not user or not user.is_authenticated:
        return
    # Toujours noter l’activité session (même hors features nommées).
    touch_last_seen(request=request, user=user)
    name = feature_name_for_path(path)
    if not name:
        return
    record_usage(name=name, user=user, path=path, request=request)
