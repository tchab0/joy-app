from __future__ import annotations

from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme


def is_safe_local_path(url: str, request: HttpRequest) -> bool:
    """Chemin relatif au site uniquement (refuse //hôte, /\\hôte, schémas)."""
    if not url or not url.startswith("/") or url.startswith(("//", "/\\")):
        return False
    return url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )
