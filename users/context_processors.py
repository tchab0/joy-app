"""Flags de navigation (haut = public/musicien, bas = staff) + config guides."""

from django.core.cache import cache

from users.nav_cache import NAV_BANNER_CACHE_TTL, nav_banner_cache_key
from users.page_leads import get_dismissed_page_leads
from users.roles import user_can_access_planning

# Namespaces du menu Coulisses (lien nav → planning).
_COULISSES_NAMESPACES = frozenset({"planning", "repertoire", "repetitions", "chat"})


def nav_access(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "show_musician_nav": False,
            "show_staff_nav": False,
            "product_tour_config": None,
            "dismissed_page_leads": set(),
            "pending_polls": [],
            "pending_polls_count": 0,
            "unread_inbox": [],
            "unread_inbox_count": 0,
            "unread_inbox_banner": {
                "chat_groups": [],
                "chat_total": 0,
                "other": [],
            },
            "show_coulisses_unread_banner": False,
        }

    from users.tour_service import build_tour_config

    show_musician_nav = user_can_access_planning(user)
    pending_polls = []
    unread_inbox: list = []
    unread_inbox_count = 0
    unread_inbox_banner = {
        "chat_groups": [],
        "chat_total": 0,
        "other": [],
    }
    match = getattr(request, "resolver_match", None)
    ns = getattr(match, "namespace", None) or ""
    url_name = getattr(match, "url_name", None) or ""
    in_coulisses = ns in _COULISSES_NAMESPACES
    # La page de détail affiche déjà le sondage complet.
    show_poll_banner = not (ns == "planning" and url_name == "poll_detail")

    if show_musician_nav:
        from planning.services import pending_polls_for_user
        from users.notify import (
            group_unread_inbox_for_banner,
            unread_notification_count_for_user,
            unread_notifications_for_user,
        )

        cache_key = nav_banner_cache_key(user.pk)
        banner_payload = cache.get(cache_key)
        if banner_payload is None:
            unread_inbox_count = unread_notification_count_for_user(user)
            # Toujours calculer + cacher les IDs ; masquer seulement le rendu
            # sur la page détail du sondage (déjà affiché en plein).
            pending_polls = pending_polls_for_user(user)
            banner_payload = {
                "poll_ids": [poll.pk for poll in pending_polls],
                "unread_inbox_count": unread_inbox_count,
            }
            cache.set(cache_key, banner_payload, NAV_BANNER_CACHE_TTL)
        else:
            unread_inbox_count = int(banner_payload.get("unread_inbox_count", 0))
            pending_polls = pending_polls_for_user(
                user,
                proposal_ids=banner_payload.get("poll_ids", []),
            )
        if not show_poll_banner:
            pending_polls = []

        if in_coulisses and unread_inbox_count:
            unread_inbox, unread_inbox_count = unread_notifications_for_user(
                user,
                total=unread_inbox_count,
            )
            unread_inbox_banner = group_unread_inbox_for_banner(unread_inbox)

    return {
        "show_musician_nav": show_musician_nav,
        "show_staff_nav": bool(user.is_staff or user.is_superuser),
        "product_tour_config": build_tour_config(request),
        "dismissed_page_leads": get_dismissed_page_leads(user),
        "pending_polls": pending_polls,
        "pending_polls_count": len(pending_polls),
        "unread_inbox": unread_inbox,
        "unread_inbox_count": unread_inbox_count,
        "unread_inbox_banner": unread_inbox_banner,
        "show_coulisses_unread_banner": bool(
            show_musician_nav and unread_inbox and in_coulisses
        ),
    }
