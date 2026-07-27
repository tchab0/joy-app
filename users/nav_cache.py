"""Cache court des compteurs de navigation par utilisateur."""

from django.core.cache import cache

NAV_BANNER_CACHE_TTL = 45


def nav_banner_cache_key(user_id: int) -> str:
    return f"users:nav-banner:{user_id}"


def invalidate_nav_banner_cache(user_or_id) -> None:
    """Invalide le résumé de bannière après une action utilisateur."""
    user_id = getattr(user_or_id, "pk", user_or_id)
    if user_id is not None:
        cache.delete(nav_banner_cache_key(int(user_id)))
