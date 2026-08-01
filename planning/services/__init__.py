"""Helpers métier pour le planning musiciens (API publique inchangée)."""
from __future__ import annotations

from planning.services.constants import (  # noqa: F401
    DEFAULT_BIG_BAND_EQUIPMENT,
    EQUIPMENT_CATEGORIES,
    RESPOND_MAP,
    STATUS_CODES,
)
from planning.services import constants as _constants
from planning.services._notify import notify_users  # noqa: F401

from planning.services.calendar_ops import (
    calendar_summaries_for_events,
    attach_calendar_summaries,
    calendar_chat_links_for_user,
    attach_calendar_chat_links,
    attach_calendar_setlists,
    attach_calendar_roadmaps,
    chat_link_for_event,
)
from planning.services.equipment import (
    ensure_default_equipment,
    get_or_create_equipment_item,
)
from planning.services.invites import (
    titulaires_queryset,
    resolve_invite_slot,
    invite_slots_for_profile,
    invite_choices_for_musicians,
    invite_musicians_for_form,
    parse_invite_choice,
    invite_titulaires_to_event,
    notify_event_invite,
    send_event_photos_requests,
    invite_musician_to_event,
    propose_event,
)
from planning.services.musicians import (
    get_or_create_profile,
)
from planning.services.polls import (
    poll_notification_recipients,
    notify_availability_poll,
    notify_poll_deadline_reminder,
    send_due_poll_deadline_reminders,
    launch_availability_poll,
    lock_date_proposal,
    vote_counts_for_option,
    format_poll_vote_counts,
    user_can_access_poll,
    user_has_answered_poll,
    pending_polls_for_user,
    CalendarPollMarker,
    open_poll_calendar_markers_for_user,
    attach_open_poll_info_to_events,
    cast_date_vote,
    draft_proposal_for_event,
    open_proposal_for_event,
    user_can_edit_poll_deadline,
)
from planning.services.roster import (
    roster_by_stage,
    remplacants_for_poste,
    attach_roster_substitutes,
    remplacants_by_section_code,
)
from planning.services.rsvp import (
    apply_maybe_remind_schedule,
    clear_maybe_remind_schedule,
    set_participation_response,
    notify_maybe_remind,
    send_due_maybe_reminds,
    notify_staff_presence_invalidated,
    get_participation_for,
    require_participation,
)
from planning.services.status import (
    ensure_participation_statuses,
    get_status,
)
from planning.services.roadmap import (
    apply_suggestion,
    get_or_create_roadmap,
    get_roadmap,
    notify_roadmap,
    suggest_defaults,
    sync_known_fields,
    user_can_view_roadmap,
)
from planning.services.substitutes import (
    eligible_substitutes_for,
    propose_substitute,
    respond_substitute_request,
)


def __getattr__(name: str):
    if name == "_STATUS_CACHE":
        return _constants._STATUS_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
