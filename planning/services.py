"""Helpers métier pour le planning musiciens."""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
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


def titulaires_queryset():
    """Musiciens actifs ayant un poste titulaire renseigné."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.filter(
        is_musician=True,
        is_active=True,
        musician_profile__poste_titulaire__gt="",
    )


def invite_titulaires_to_event(event) -> int:
    """Convoque tous les titulaires à une date (ignore les déjà inscrits)."""
    invited = get_status("invited")
    musicians = list(titulaires_queryset())
    existing = set(
        EventParticipation.objects.filter(event=event).values_list(
            "user_id", flat=True
        )
    )
    to_create = [
        EventParticipation(event=event, user=u, status=invited)
        for u in musicians
        if u.pk not in existing
    ]
    if to_create:
        EventParticipation.objects.bulk_create(to_create, ignore_conflicts=True)
        # bulk_create ne déclenche pas post_save → sync chat manuelle
        from chat.services import sync_participation_to_chat

        for part in EventParticipation.objects.filter(
            event=event, user_id__in=[p.user_id for p in to_create]
        ):
            sync_participation_to_chat(part)
    return len(to_create)


def eligible_substitutes_for(participation: EventParticipation):
    """Remplaçants du même pupitre non déjà inscrits confirmés / invités."""
    try:
        profile = participation.user.musician_profile
        section = profile.section
    except MusicianProfile.DoesNotExist:
        section = None

    qs = MusicianProfile.objects.select_related("user", "section").filter(
        user__is_active=True,
        user__is_musician=True,
        poste_remplacant__gt="",
    ).exclude(user_id=participation.user_id)

    if section is not None:
        qs = qs.filter(section=section)

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


def _is_concert_type(event) -> bool:
    nom = (getattr(getattr(event, "type", None), "nom", None) or "").strip().lower()
    return "concert" in nom


def _expected_sections() -> list[OrchestraSection]:
    """Pupitres actifs pour lesquels au moins un titulaire est en roster."""
    return list(
        OrchestraSection.objects.filter(
            is_active=True,
            musicians__poste_titulaire__gt="",
            musicians__user__is_active=True,
            musicians__user__is_musician=True,
        )
        .distinct()
        .order_by("sort_order", "name")
    )


def calendar_summaries_for_events(events) -> dict[int, dict]:
    """
    Résumés calendrier (présence + pupitres manquants), indexés par event.pk.

    Présents = participations confirmées, ventilées titulaire / remplaçant.
    Instruments manquants = pupitres attendus sans aucun confirmé.
    """
    events = list(events)
    if not events:
        return {}

    expected = _expected_sections()
    expected_ids = {s.pk for s in expected}
    by_event_confirmed: dict[int, list] = defaultdict(list)

    parts = (
        EventParticipation.objects.filter(
            event_id__in=[e.pk for e in events],
            status__code="confirmed",
        )
        .select_related("user__musician_profile__section")
        .order_by("pk")
    )
    for p in parts:
        by_event_confirmed[p.event_id].append(p)

    summaries: dict[int, dict] = {}
    for event in events:
        confirmed = by_event_confirmed.get(event.pk, [])
        n_tit = 0
        n_rem = 0
        covered_section_ids: set[int] = set()
        for p in confirmed:
            try:
                profile = p.user.musician_profile
            except MusicianProfile.DoesNotExist:
                profile = None
            if profile is not None and profile.is_remplacant and not profile.is_titulaire:
                n_rem += 1
            else:
                n_tit += 1
            if profile is not None and profile.section_id in expected_ids:
                covered_section_ids.add(profile.section_id)

        missing = [s.name for s in expected if s.pk not in covered_section_ids]
        local_start = timezone.localtime(event.date_debut)
        venue = event.venue
        lieu = ""
        if venue is not None:
            lieu = f"{venue.nom} — {venue.ville}" if venue.ville else venue.nom

        summaries[event.pk] = {
            "titre": event.titre,
            "is_concert": _is_concert_type(event),
            "type_nom": getattr(getattr(event, "type", None), "nom", "") or "",
            "date_label": local_start.strftime("%d/%m/%Y"),
            "time_label": local_start.strftime("%H:%M"),
            "lieu": lieu,
            "n_titulaires": n_tit,
            "n_remplacants": n_rem,
            "n_presents": n_tit + n_rem,
            "instruments_manquants": missing,
            "instruments_manquants_label": (
                ", ".join(missing) if missing else "Aucun"
            ),
        }
    return summaries


def attach_calendar_summaries(events) -> list:
    """Attache ``event.cal_summary`` à chaque événement (mutates in place)."""
    summaries = calendar_summaries_for_events(events)
    for event in events:
        event.cal_summary = summaries.get(event.pk, {})
    return list(events)
