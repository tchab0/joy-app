"""Rôles JOY exposés aux votes et au contexte des retours."""

from __future__ import annotations

from users.roles import (
    ROLE_LABELS,
    ROLE_MEMBER,
    ROLE_MUSICIAN,
    ROLE_STAFF,
    get_user_roles,
)

# Alias pour compatibilité avec le service Skillsciel adapté.
NAV_PROFILE_ADMIN = ROLE_STAFF

VOTE_ROLE_LABELS = {
    ROLE_MUSICIAN: ROLE_LABELS[ROLE_MUSICIAN],
    ROLE_MEMBER: ROLE_LABELS[ROLE_MEMBER],
    ROLE_STAFF: ROLE_LABELS[ROLE_STAFF],
}


def get_available_vote_roles(user) -> list[str]:
    return sorted(get_user_roles(user) & set(VOTE_ROLE_LABELS))


def role_labels_for_user(user) -> dict[str, str]:
    roles = get_user_roles(user)
    return {key: VOTE_ROLE_LABELS[key] for key in VOTE_ROLE_LABELS if key in roles}
