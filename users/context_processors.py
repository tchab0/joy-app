"""Flags de navigation (haut = public/musicien, bas = staff) + config guides."""

from users.page_leads import get_dismissed_page_leads
from users.roles import user_can_access_planning


def nav_access(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "show_musician_nav": False,
            "show_staff_nav": False,
            "product_tour_config": None,
            "dismissed_page_leads": set(),
        }

    from users.tour_service import build_tour_config

    return {
        "show_musician_nav": user_can_access_planning(user),
        "show_staff_nav": bool(user.is_staff or user.is_superuser),
        "product_tour_config": build_tour_config(request),
        "dismissed_page_leads": get_dismissed_page_leads(user),
    }
