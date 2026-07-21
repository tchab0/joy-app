"""Flags de navigation (haut = public/musicien, bas = staff)."""

from users.roles import user_can_access_planning


def nav_access(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "show_musician_nav": False,
            "show_staff_nav": False,
        }
    return {
        "show_musician_nav": user_can_access_planning(user),
        "show_staff_nav": bool(user.is_staff or user.is_superuser),
    }
