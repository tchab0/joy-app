"""Helpers métier pour le planning musiciens."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EventParticipation,
    MusicianProfile,
    ParticipationStatus,
    SubstituteRequest,
)


STATUS_CODES = {
    "invited": {"label": "Invité", "color_token": "warning", "sort_order": 10},
    "confirmed": {"label": "Confirmé", "color_token": "success", "sort_order": 20},
    "maybe": {"label": "Peut-être", "color_token": "warning", "sort_order": 25},
    "declined": {"label": "Refusé", "color_token": "danger", "sort_order": 30},
    "replacement_needed": {
        "label": "Remplacement demandé",
        "color_token": "neutral",
        "sort_order": 40,
    },
}

RESPOND_MAP = {
    "yes": "confirmed",
    "no": "declined",
    "maybe": "maybe",
}


def ensure_participation_statuses() -> dict[str, ParticipationStatus]:
    result: dict[str, ParticipationStatus] = {}
    for code, payload in STATUS_CODES.items():
        status, _ = ParticipationStatus.objects.update_or_create(
            code=code,
            defaults={
                "label": payload["label"],
                "color_token": payload["color_token"],
                "sort_order": payload["sort_order"],
                "is_active": True,
            },
        )
        result[code] = status
    return result


def get_status(code: str) -> ParticipationStatus:
    statuses = ensure_participation_statuses()
    return statuses[code]


def get_or_create_profile(user) -> MusicianProfile:
    profile, _ = MusicianProfile.objects.get_or_create(user=user)
    return profile


def set_participation_response(
    participation: EventParticipation,
    response: str,
    *,
    comment: str = "",
) -> EventParticipation:
    if response not in RESPOND_MAP:
        raise ValueError("Réponse invalide")
    participation.status = get_status(RESPOND_MAP[response])
    if comment:
        participation.comment = comment
    participation.save(update_fields=["status", "comment", "updated_at"])
    return participation


def eligible_substitutes_for(participation: EventParticipation):
    """Musiciens du même pupitre (ou pool) non déjà inscrits confirmés."""
    try:
        profile = participation.user.musician_profile
        section = profile.section
    except MusicianProfile.DoesNotExist:
        section = None

    qs = MusicianProfile.objects.select_related("user", "section").filter(
        user__is_active=True,
        user__is_musician=True,
    ).exclude(user_id=participation.user_id)

    if section is not None:
        qs = qs.filter(Q(section=section) | Q(is_substitute_pool=True))
    else:
        qs = qs.filter(is_substitute_pool=True)

    taken_ids = set(
        EventParticipation.objects.filter(
            event=participation.event,
            status__code__in=["confirmed", "invited", "maybe"],
        ).values_list("user_id", flat=True)
    )
    return [p for p in qs.distinct() if p.user_id not in taken_ids]


@transaction.atomic
def propose_substitute(
    participation: EventParticipation,
    candidate,
    *,
    note: str = "",
) -> SubstituteRequest:
    if candidate.pk == participation.user_id:
        raise ValueError("Impossible de se proposer soi-même")
    participation.status = get_status("replacement_needed")
    participation.save(update_fields=["status", "updated_at"])
    req, _ = SubstituteRequest.objects.update_or_create(
        participation=participation,
        candidate=candidate,
        defaults={
            "status": SubstituteRequest.Status.PROPOSED,
            "note": note,
        },
    )
    return req


@transaction.atomic
def respond_substitute_request(
    request_obj: SubstituteRequest,
    *,
    accept: bool,
) -> SubstituteRequest:
    if request_obj.status != SubstituteRequest.Status.PROPOSED:
        raise ValueError("Demande déjà traitée")

    if accept:
        request_obj.status = SubstituteRequest.Status.ACCEPTED
        request_obj.save(update_fields=["status", "updated_at"])
        confirmed = get_status("confirmed")
        declined = get_status("declined")
        EventParticipation.objects.update_or_create(
            event=request_obj.participation.event,
            user=request_obj.candidate,
            defaults={"status": confirmed, "comment": "Remplaçant"},
        )
        orig = request_obj.participation
        orig.status = declined
        orig.save(update_fields=["status", "updated_at"])
        SubstituteRequest.objects.filter(
            participation=orig,
            status=SubstituteRequest.Status.PROPOSED,
        ).exclude(pk=request_obj.pk).update(
            status=SubstituteRequest.Status.CANCELLED
        )
    else:
        request_obj.status = SubstituteRequest.Status.DECLINED
        request_obj.save(update_fields=["status", "updated_at"])
    return request_obj


@transaction.atomic
def lock_date_proposal(
    proposal: DateProposal,
    option: DateOption,
    *,
    event,
) -> DateProposal:
    if option.proposal_id != proposal.pk:
        raise ValueError("Option hors sondage")
    proposal.locked_option = option
    proposal.linked_event = event
    proposal.status = DateProposal.Status.LOCKED
    proposal.save(
        update_fields=["locked_option", "linked_event", "status", "updated_at"]
    )
    return proposal


def vote_counts_for_option(option: DateOption) -> dict[str, int]:
    counts = {"yes": 0, "no": 0, "maybe": 0}
    for choice in option.votes.values_list("choice", flat=True):
        if choice in counts:
            counts[choice] += 1
    return counts


def cast_date_vote(option: DateOption, user, choice: str) -> DateVote:
    if choice not in DateVote.Choice.values:
        raise ValueError("Vote invalide")
    proposal = option.proposal
    if not proposal.is_open:
        raise ValueError("Sondage fermé")
    vote, _ = DateVote.objects.update_or_create(
        option=option,
        user=user,
        defaults={"choice": choice},
    )
    return vote


def get_participation_for(event, user) -> EventParticipation | None:
    return (
        EventParticipation.objects.select_related("status")
        .filter(event=event, user=user)
        .first()
    )


def require_participation(event, user) -> EventParticipation:
    return get_object_or_404(
        EventParticipation.objects.select_related("status"),
        event=event,
        user=user,
    )
