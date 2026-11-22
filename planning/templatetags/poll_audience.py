"""Filtres / tags pour l’intention d’audience des sondages."""

from __future__ import annotations

from django import template

from planning.services.polls import (
    POLL_AUDIENCE_ALL_LABEL,
    POLL_AUDIENCE_ROOM_LABEL,
    poll_audience_help,
    poll_audience_label,
    poll_recipient_count,
)

register = template.Library()


@register.simple_tag
def poll_audience_all_label() -> str:
    return POLL_AUDIENCE_ALL_LABEL


@register.simple_tag
def poll_audience_room_label() -> str:
    return POLL_AUDIENCE_ROOM_LABEL


@register.filter
def audience_label(audience: str | None) -> str:
    return poll_audience_label(audience)


@register.filter
def audience_help(audience: str | None) -> str:
    return poll_audience_help(audience)


@register.filter
def audience_help_event(audience: str | None) -> str:
    return poll_audience_help(audience, for_event=True)


@register.filter
def recipient_count(proposal) -> int:
    if proposal is None:
        return 0
    return poll_recipient_count(proposal)
