"""Flags de navigation (haut = public/musicien, bas = staff) + config guides."""

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
    if show_musician_nav:
        from planning.services import pending_polls_for_user
        from users.notify import (
            group_unread_inbox_for_banner,
            unread_notifications_for_user,
        )

        pending_polls = pending_polls_for_user(user)
        unread_inbox, unread_inbox_count = unread_notifications_for_user(user)
        unread_inbox_banner = group_unread_inbox_for_banner(unread_inbox)

    match = getattr(request, "resolver_match", None)
    ns = getattr(match, "namespace", None) or ""
    in_coulisses = ns in _COULISSES_NAMESPACES

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
