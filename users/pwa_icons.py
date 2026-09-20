"""URLs d’icônes PWA / Web Push — versionnées pour casser le cache navigateur."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings

_ICON_REL = "users/icons/icon-192.png"
_ICON_512_REL = "users/icons/icon-512.png"
_PLACEHOLDER = "__JOY_ICON_VERSION__"


@lru_cache(maxsize=1)
def icon_content_version() -> str:
    """Hash court du PNG 192 — invalide le cache quand le logo change."""
    path = Path(settings.BASE_DIR) / "users" / "static" / _ICON_REL
    try:
        digest = hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return "1"
    return digest[:10]


def bust_cache(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}v={icon_content_version()}"


def icon_192_path() -> str:
    return bust_cache(f"/static/{_ICON_REL}")


def icon_512_path() -> str:
    return bust_cache(f"/static/{_ICON_512_REL}")


def absolute_icon_192() -> str:
    site = getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip(
        "/"
    )
    return f"{site}{icon_192_path()}"


def inject_sw_icon_version(source: str) -> str:
    return source.replace(_PLACEHOLDER, icon_content_version())
