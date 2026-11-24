"""Limitation de débit simple sur le cache Django (Redis en prod)."""

from __future__ import annotations

import hashlib

from django.core.cache import cache
from django.http import HttpRequest

HONEYPOT_FIELD = "website"

# Fenêtre anti-double-soumission HTTP (clics répétés / retries rapides).
MUTATING_SUBMIT_WINDOW = 8
# Fenêtre anti-doublon notifications métier (même objet lié).
NOTIFY_DEDUP_WINDOW = 120


def client_ip(request: HttpRequest) -> str:
    # nginx écrase X-Real-IP avec $remote_addr ; gunicorn écoute sur un socket unix.
    return (
        request.META.get("HTTP_X_REAL_IP")
        or request.META.get("REMOTE_ADDR")
        or "unknown"
    ).strip()


def _key(scope: str, ident: str) -> str:
    digest = hashlib.sha256(ident.strip().lower().encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def is_limited(scope: str, ident: str, limit: int) -> bool:
    return int(cache.get(_key(scope, ident)) or 0) >= limit


def hit(scope: str, ident: str, window: int) -> int:
    key = _key(scope, ident)
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=window)
        return 1


def consume(scope: str, ident: str, limit: int, window: int) -> bool:
    """Compte une tentative ; False si la limite était déjà atteinte."""
    if is_limited(scope, ident, limit):
        return False
    hit(scope, ident, window)
    return True


def claim_once(scope: str, ident: str, window: int) -> bool:
    """
    Réserve un jeton unique pour ``ident`` pendant ``window`` secondes.

    True = première tentative (à traiter). False = doublon / double-clic.
    Atomique via ``cache.add`` (Redis en prod).
    """
    return bool(cache.add(_key(scope, ident), 1, timeout=max(1, int(window))))


def reset(scope: str, ident: str) -> None:
    cache.delete(_key(scope, ident))


def honeypot_triggered(request: HttpRequest) -> bool:
    return bool((request.POST.get(HONEYPOT_FIELD) or "").strip())


def mutate_fingerprint(request: HttpRequest) -> str:
    """Empreinte stable d’une requête mutante (méthode + chemin + corps)."""
    raw = getattr(request, "body", b"") or b""
    # Limite la taille hashée (uploads).
    sample = raw[:65536]
    body_digest = hashlib.sha256(sample).hexdigest()[:20]
    length = request.META.get("CONTENT_LENGTH") or len(raw)
    return (
        f"{request.method}:{request.path}:{length}:{body_digest}"
    )


def claim_mutating_request(
    request: HttpRequest, *, window: int = MUTATING_SUBMIT_WINDOW
) -> bool:
    """
    True si cette mutation authentifiée est nouvelle dans la fenêtre.
    False = doublon à ignorer.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return True
    uid = getattr(user, "pk", None)
    if uid is None:
        return True
    return claim_once(
        "http_mut",
        f"{uid}:{mutate_fingerprint(request)}",
        window,
    )


def claim_notify_once(
    *,
    related_type: str,
    related_id: int | None,
    title: str,
    body: str = "",
    window: int = NOTIFY_DEDUP_WINDOW,
) -> bool:
    """Empêche un second envoi notify_users pour le même objet / contenu."""
    rtype = (related_type or "").strip()
    if not rtype or related_id is None:
        return True
    sig = hashlib.sha256(
        f"{rtype}:{int(related_id)}:{(title or '').strip()}|{(body or '').strip()}".encode()
    ).hexdigest()[:24]
    return claim_once("notify", sig, window)
