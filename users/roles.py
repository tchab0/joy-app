"""Résolution de rôles et permissions — mise en cache sur l’instance request.user."""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

ROLE_MUSICIAN = "musician"
ROLE_MEMBER = "association_member"
ROLE_STAFF = "staff"

GROUP_MUSICIAN = "Musiciens"
GROUP_MEMBER = "Adhérents"

ROLE_LABELS = {
    ROLE_MUSICIAN: "Musicien",
    ROLE_MEMBER: "Adhérent",
    ROLE_STAFF: "Staff",
}


def get_user_roles(user) -> frozenset[str]:
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    cached = getattr(user, "_cached_roles", None)
    if cached is not None:
        return cached

    roles: set[str] = set()
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        roles.add(ROLE_STAFF)
    if getattr(user, "is_musician", False):
        roles.add(ROLE_MUSICIAN)
    if getattr(user, "membership_active", False):
        roles.add(ROLE_MEMBER)

    result = frozenset(roles)
    user._cached_roles = result
    return result


def user_has_role(user, role: str) -> bool:
    return role in get_user_roles(user)


def user_has_any_role(user, *roles: str) -> bool:
    user_roles = get_user_roles(user)
    return any(role in user_roles for role in roles)


def user_can_access_planning(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    # Flags métier d’abord (source de vérité) ; permissions Django en complément.
    if user_has_role(user, ROLE_MUSICIAN):
        return True
    return user.has_perm("users.access_planning")


def user_can_access_member_area(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user_has_role(user, ROLE_MEMBER):
        return True
    return user.has_perm("users.access_member_area")


def sync_user_groups(user) -> None:
    """Aligne les Groupes Django sur les flags métier (admin + permissions)."""
    from django.contrib.auth.models import Group

    musician_group, _ = Group.objects.get_or_create(name=GROUP_MUSICIAN)
    member_group, _ = Group.objects.get_or_create(name=GROUP_MEMBER)

    if user.is_musician:
        user.groups.add(musician_group)
    else:
        user.groups.remove(musician_group)

    if user.membership_active:
        user.groups.add(member_group)
    else:
        user.groups.remove(member_group)

    user.clear_role_cache()


def role_required(*roles: str, login_url: str | None = None):
    """Décorateur de vue : exige au moins un des rôles."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path(), login_url=login_url)
            if request.user.is_superuser or user_has_any_role(request.user, *roles):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied

        return _wrapped

    return decorator


class RoleRequiredMixin(AccessMixin):
    """Mixin CBV : `required_roles` = iterable de rôles (OU logique)."""

    required_roles: Iterable[str] = ()
    permission_denied_message = "Vous n’avez pas les droits nécessaires."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if self.required_roles and not user_has_any_role(
            request.user, *self.required_roles
        ):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class MusicianRequiredMixin(AccessMixin):
    permission_denied_message = "Accès réservé aux musiciens."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_can_access_planning(request.user):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class MemberRequiredMixin(AccessMixin):
    permission_denied_message = "Accès réservé aux adhérents."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_can_access_member_area(request.user):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
