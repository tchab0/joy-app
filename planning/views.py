from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import AccessMixin
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View
from django.views.generic import TemplateView

from events.models import Event, EventType, Venue
from planning.models import (
    DateOption,
    DateProposal,
    EquipmentItem,
    EventEquipmentAssignment,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    SubstituteRequest,
)
from planning.services import (
    cast_date_vote,
    eligible_substitutes_for,
    ensure_participation_statuses,
    get_or_create_profile,
    get_participation_for,
    invite_titulaires_to_event,
    lock_date_proposal,
    propose_substitute,
    respond_substitute_request,
    set_participation_response,
    vote_counts_for_option,
)
from users.roles import MusicianRequiredMixin, user_can_access_planning

User = get_user_model()

_FRENCH_MONTHS = (
    "",
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
)
_WEEKDAY_LABELS = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


def _build_year_calendar(year: int, events_by_day: dict[date, list]) -> list[dict]:
    """Grille des 12 mois : chaque jour de l’année (lundi → dimanche)."""
    today = timezone.localdate()
    cal = calendar.Calendar(firstweekday=0)
    months: list[dict] = []
    for month in range(1, 13):
        weeks = []
        for week in cal.monthdayscalendar(year, month):
            days = []
            for day_num in week:
                if day_num == 0:
                    days.append(None)
                    continue
                day = date(year, month, day_num)
                days.append(
                    {
                        "date": day,
                        "iso": day.isoformat(),
                        "day": day_num,
                        "events": events_by_day.get(day, []),
                        "is_today": day == today,
                        "is_past": day < today,
                    }
                )
            weeks.append(days)
        months.append(
            {
                "number": month,
                "name": _FRENCH_MONTHS[month],
                "weeks": weeks,
            }
        )
    return months


class PlanningStaffRequiredMixin(AccessMixin):
    """Staff Django uniquement pour l’admin planning."""

    permission_denied_message = "Accès réservé au staff."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_staff or request.user.is_superuser):
            return self.handle_no_permission()
        if not user_can_access_planning(request.user):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_json_body(request: HttpRequest) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode() or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST.dict()


# ---------------------------------------------------------------------------
# Musician-facing pages
# ---------------------------------------------------------------------------


class PlanningDashboardView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ensure_participation_statuses()
        user = self.request.user
        now = timezone.now()

        my_parts = (
            EventParticipation.objects.filter(
                user=user,
                event__date_debut__gte=now,
                event__statut__in=[Event.Statut.CONFIRME, Event.Statut.TENTATIVE],
            )
            .select_related("event", "event__venue", "event__type", "status")
            .order_by("event__date_debut")[:20]
        )

        pending = [p for p in my_parts if p.status.code in ("invited", "maybe")]
        upcoming = list(my_parts)

        open_polls = (
            DateProposal.objects.filter(status=DateProposal.Status.OPEN)
            .prefetch_related("options")
            .order_by("-created_at")[:10]
        )

        sub_offers = (
            SubstituteRequest.objects.filter(
                candidate=user,
                status=SubstituteRequest.Status.PROPOSED,
                participation__event__date_debut__gte=now,
            )
            .select_related(
                "participation",
                "participation__event",
                "participation__user",
            )
            .order_by("participation__event__date_debut")
        )

        my_gear = (
            EventEquipmentAssignment.objects.filter(
                assigned_to=user,
                event__date_debut__gte=now,
            )
            .select_related("event", "item")
            .order_by("event__date_debut")[:15]
        )

        context.update(
            {
                "pending": pending,
                "upcoming": upcoming,
                "open_polls": open_polls,
                "sub_offers": sub_offers,
                "my_gear": my_gear,
                "profile": get_or_create_profile(user),
                "sections": OrchestraSection.objects.filter(is_active=True),
                "is_planning_staff": user.is_staff or user.is_superuser,
            }
        )
        return context


class PlanningYearCalendarView(MusicianRequiredMixin, TemplateView):
    """Planning par défaut : tous les jours des 12 mois de l’année."""

    template_name = "planning/upcoming_12_months.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        try:
            year = int(self.request.GET.get("year") or timezone.localdate().year)
        except (TypeError, ValueError):
            year = timezone.localdate().year
        year = max(2000, min(2100, year))

        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(date(year, 1, 1), time.min), tz)
        end = timezone.make_aware(
            datetime.combine(date(year, 12, 31), time.max), tz
        )
        events = (
            Event.objects.filter(date_debut__gte=start, date_debut__lte=end)
            .select_related("type", "venue")
            .order_by("date_debut", "titre")
        )
        events_by_day: dict[date, list] = defaultdict(list)
        for event in events:
            events_by_day[timezone.localtime(event.date_debut).date()].append(event)

        is_staff = user.is_staff or user.is_superuser
        context.update(
            {
                "calendar_year": year,
                "prev_year": year - 1,
                "next_year": year + 1,
                "weekday_labels": _WEEKDAY_LABELS,
                "months": _build_year_calendar(year, events_by_day),
                "is_planning_staff": is_staff,
                "venues": Venue.objects.all().order_by("ville", "nom") if is_staff else [],
                "event_types": EventType.objects.all().order_by("nom") if is_staff else [],
            }
        )
        return context


# Alias conservé pour les URLs / tests existants.
PlanningUpcomingView = PlanningYearCalendarView


class CreateEventView(PlanningStaffRequiredMixin, View):
    """Création d’un événement à partir d’un jour du calendrier."""

    def post(self, request):
        titre = (request.POST.get("titre") or "").strip()
        venue_id = request.POST.get("venue_id")
        type_id = request.POST.get("type_id")
        day_raw = (request.POST.get("date") or "").strip()
        time_raw = (request.POST.get("time") or "20:00").strip() or "20:00"

        if not titre or not venue_id or not type_id or not day_raw:
            messages.error(request, "Titre, date, lieu et type sont requis.")
            return redirect(self._calendar_url(day_raw))

        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            messages.error(request, "Date invalide.")
            return redirect("planning:dashboard")

        try:
            hour, minute = (int(x) for x in time_raw.split(":")[:2])
            starts = timezone.make_aware(datetime.combine(day, time(hour, minute)))
        except (ValueError, TypeError):
            messages.error(request, "Heure invalide.")
            return redirect(self._calendar_url(day_raw))

        venue = get_object_or_404(Venue, pk=venue_id)
        event_type = get_object_or_404(EventType, pk=type_id)
        public = request.POST.get("public") == "on"
        description = (request.POST.get("description") or "").strip()

        event = Event.objects.create(
            titre=titre,
            type=event_type,
            venue=venue,
            date_debut=starts,
            description=description,
            statut=Event.Statut.TENTATIVE,
            public=public,
        )
        messages.success(
            request,
            f"Événement « {event.titre} » créé — titulaires convoqués.",
        )
        return redirect("planning:event_roster", pk=event.pk)

    @staticmethod
    def _calendar_url(day_raw: str) -> str:
        try:
            year = date.fromisoformat(day_raw).year
            return f"{reverse('planning:dashboard')}?year={year}"
        except ValueError:
            return reverse("planning:dashboard")


class EventDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/event_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(
            Event.objects.select_related("venue", "type"),
            pk=kwargs["pk"],
        )
        user = self.request.user
        participation = get_participation_for(event, user)

        parts = (
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__musician_profile__section__sort_order",
                "user__last_name",
                "user__first_name",
            )
        )
        by_section: dict[str, list] = defaultdict(list)
        counts = {"confirmed": 0, "invited": 0, "maybe": 0, "declined": 0, "replacement_needed": 0}
        for p in parts:
            section_name = "Sans pupitre"
            try:
                if p.user.musician_profile.section:
                    section_name = p.user.musician_profile.section.name
            except MusicianProfile.DoesNotExist:
                pass
            by_section[section_name].append(p)
            if p.status.code in counts:
                counts[p.status.code] += 1

        eligible = eligible_substitutes_for(participation) if participation else []
        my_sub_requests = []
        if participation:
            my_sub_requests = list(
                participation.substitute_requests.select_related("candidate").order_by(
                    "-created_at"
                )
            )

        gear = (
            EventEquipmentAssignment.objects.filter(event=event)
            .select_related("item", "assigned_to")
            .order_by("item__sort_order", "item__name")
        )

        context.update(
            {
                "event": event,
                "participation": participation,
                "by_section": dict(by_section),
                "counts": counts,
                "eligible_subs": eligible,
                "my_sub_requests": my_sub_requests,
                "gear": gear,
                "is_planning_staff": user.is_staff or user.is_superuser,
            }
        )
        return context


class PollDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/poll_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        proposal = get_object_or_404(
            DateProposal.objects.prefetch_related(
                Prefetch(
                    "options",
                    queryset=DateOption.objects.prefetch_related("votes").order_by(
                        "sort_order", "starts_at"
                    ),
                )
            ),
            pk=kwargs["pk"],
        )
        user = self.request.user
        options_data = []
        for opt in proposal.options.all():
            my_vote = next((v for v in opt.votes.all() if v.user_id == user.pk), None)
            counts = vote_counts_for_option(opt)
            options_data.append(
                {
                    "option": opt,
                    "counts": counts,
                    "counts_json": json.dumps(counts),
                    "my_vote": my_vote.choice if my_vote else None,
                }
            )
        context.update(
            {
                "proposal": proposal,
                "options_data": options_data,
                "is_planning_staff": user.is_staff or user.is_superuser,
                "venues": Venue.objects.all().order_by("ville", "nom"),
                "event_types": EventType.objects.all().order_by("nom"),
            }
        )
        return context


# ---------------------------------------------------------------------------
# JSON / action endpoints (musicians)
# ---------------------------------------------------------------------------


class RespondParticipationView(MusicianRequiredMixin, View):
    def post(self, request, pk):
        participation = get_object_or_404(
            EventParticipation.objects.select_related("status", "event"),
            pk=pk,
            user=request.user,
        )
        data = _parse_json_body(request)
        response = data.get("response", "")
        try:
            set_participation_response(
                participation,
                response,
                comment=data.get("comment", "") or "",
            )
        except ValueError as exc:
            return _json_error(str(exc))
        participation.refresh_from_db()
        return JsonResponse(
            {
                "ok": True,
                "status": {
                    "code": participation.status.code,
                    "label": participation.status.label,
                    "color_token": participation.status.color_token,
                },
            }
        )


class ProposeSubstituteView(MusicianRequiredMixin, View):
    def post(self, request, pk):
        participation = get_object_or_404(
            EventParticipation.objects.select_related("user", "event"),
            pk=pk,
            user=request.user,
        )
        data = _parse_json_body(request)
        candidate_id = data.get("candidate_id")
        if not candidate_id:
            return _json_error("Candidat requis")
        candidate = get_object_or_404(User, pk=candidate_id, is_musician=True)
        try:
            req = propose_substitute(
                participation,
                candidate,
                note=data.get("note", "") or "",
            )
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse(
            {
                "ok": True,
                "request_id": req.pk,
                "candidate": str(candidate),
                "status": req.status,
            }
        )


class ClaimSubstituteView(MusicianRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(
            SubstituteRequest.objects.select_related(
                "participation", "participation__event", "candidate"
            ),
            pk=pk,
            candidate=request.user,
        )
        data = _parse_json_body(request)
        accept = str(data.get("accept", "true")).lower() in ("1", "true", "yes")
        try:
            respond_substitute_request(req, accept=accept)
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse({"ok": True, "status": req.status})


class VotePollOptionView(MusicianRequiredMixin, View):
    def post(self, request, pk):
        option = get_object_or_404(
            DateOption.objects.select_related("proposal"),
            pk=pk,
        )
        data = _parse_json_body(request)
        choice = data.get("choice", "")
        try:
            vote = cast_date_vote(option, request.user, choice)
        except ValueError as exc:
            return _json_error(str(exc))
        return JsonResponse(
            {
                "ok": True,
                "choice": vote.choice,
                "counts": vote_counts_for_option(option),
            }
        )


class UpdateEquipmentStatusView(MusicianRequiredMixin, View):
    """Le musicien assigné (ou le staff) met à jour le statut d’un item."""

    def post(self, request, pk):
        assignment = get_object_or_404(
            EventEquipmentAssignment.objects.select_related("item", "assigned_to"),
            pk=pk,
        )
        user = request.user
        if not (
            user.is_staff
            or user.is_superuser
            or assignment.assigned_to_id == user.pk
        ):
            return _json_error("Non autorisé", status=403)
        data = _parse_json_body(request)
        status = data.get("status", "")
        if status not in EventEquipmentAssignment.Status.values:
            return _json_error("Statut invalide")
        assignment.status = status
        if "notes" in data:
            assignment.notes = data.get("notes") or ""
        assignment.save(update_fields=["status", "notes"])
        return JsonResponse({"ok": True, "status": assignment.status})


# ---------------------------------------------------------------------------
# Staff admin
# ---------------------------------------------------------------------------


class PlanningAdminView(PlanningStaffRequiredMixin, TemplateView):
    template_name = "planning/admin_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        events = (
            Event.objects.filter(date_debut__gte=now)
            .select_related("venue", "type")
            .annotate(
                n_confirmed=Count(
                    "participations",
                    filter=Q(participations__status__code="confirmed"),
                ),
                n_invited=Count(
                    "participations",
                    filter=Q(participations__status__code="invited"),
                ),
                n_declined=Count(
                    "participations",
                    filter=Q(
                        participations__status__code__in=[
                            "declined",
                            "replacement_needed",
                        ]
                    ),
                ),
                n_maybe=Count(
                    "participations",
                    filter=Q(participations__status__code="maybe"),
                ),
                n_holes=Count(
                    "participations",
                    filter=Q(participations__status__code="replacement_needed"),
                ),
            )
            .order_by("date_debut")[:30]
        )
        open_polls = DateProposal.objects.filter(
            status=DateProposal.Status.OPEN
        ).annotate(n_options=Count("options"))
        sections = OrchestraSection.objects.filter(is_active=True)
        equipment = EquipmentItem.objects.filter(is_active=True)
        context.update(
            {
                "events": events,
                "open_polls": open_polls,
                "sections": sections,
                "equipment_items": equipment,
                "venues": Venue.objects.all().order_by("ville", "nom"),
                "event_types": EventType.objects.all().order_by("nom"),
            }
        )
        return context


class EventRosterView(PlanningStaffRequiredMixin, TemplateView):
    template_name = "planning/admin_roster.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(
            Event.objects.select_related("venue", "type"),
            pk=kwargs["pk"],
        )
        parts = (
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__musician_profile__section__sort_order",
                "user__last_name",
            )
        )
        by_section: dict[str, list] = defaultdict(list)
        for p in parts:
            name = "Sans pupitre"
            try:
                if p.user.musician_profile.section:
                    name = p.user.musician_profile.section.name
            except MusicianProfile.DoesNotExist:
                pass
            by_section[name].append(p)

        gear = EventEquipmentAssignment.objects.filter(event=event).select_related(
            "item", "assigned_to"
        )
        musicians = (
            User.objects.filter(is_musician=True, is_active=True)
            .select_related("musician_profile")
            .order_by("last_name", "first_name")
        )
        context.update(
            {
                "event": event,
                "by_section": dict(by_section),
                "gear": gear,
                "equipment_catalog": EquipmentItem.objects.filter(is_active=True),
                "musicians": musicians,
            }
        )
        return context


class CreatePollView(PlanningStaffRequiredMixin, View):
    def post(self, request):
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Titre requis.")
            return redirect("planning:admin")
        description = (request.POST.get("description") or "").strip()
        proposal = DateProposal.objects.create(
            title=title,
            description=description,
            created_by=request.user,
        )
        i = 0
        while True:
            starts = request.POST.get(f"option_starts_{i}")
            if not starts:
                break
            dt = _parse_local_dt(starts)
            if dt is None:
                i += 1
                continue
            ends_raw = request.POST.get(f"option_ends_{i}") or ""
            ends = _parse_local_dt(ends_raw) if ends_raw else None
            DateOption.objects.create(
                proposal=proposal,
                starts_at=dt,
                ends_at=ends,
                label=(request.POST.get(f"option_label_{i}") or "").strip(),
                sort_order=i,
            )
            i += 1
        if i == 0 or not proposal.options.exists():
            proposal.delete()
            messages.error(request, "Ajoutez au moins une option de date.")
            return redirect("planning:admin")
        messages.success(request, "Sondage créé.")
        return redirect("planning:poll_detail", pk=proposal.pk)


def _parse_local_dt(value: str):
    """Parse datetime-local (naive) or ISO into aware datetime."""
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is None:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


class LockPollView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        option_id = request.POST.get("option_id")
        option = get_object_or_404(DateOption, pk=option_id, proposal=proposal)

        venue_id = request.POST.get("venue_id")
        type_id = request.POST.get("type_id")
        if not venue_id or not type_id:
            messages.error(request, "Lieu et type requis pour créer l’événement.")
            return redirect("planning:poll_detail", pk=pk)

        venue = get_object_or_404(Venue, pk=venue_id)
        event_type = get_object_or_404(EventType, pk=type_id)
        public = request.POST.get("public") == "on"
        event = Event.objects.create(
            titre=proposal.title,
            type=event_type,
            venue=venue,
            date_debut=option.starts_at,
            date_fin=option.ends_at,
            description=proposal.description,
            statut=Event.Statut.TENTATIVE,
            public=public,
        )
        # Les titulaires sont convoqués automatiquement (signal post_save).
        lock_date_proposal(proposal, option, event=event)
        n_invited = EventParticipation.objects.filter(event=event).count()
        messages.success(
            request,
            f"Date verrouillée — événement « {event.titre} » créé "
            f"({n_invited} titulaire{'s' if n_invited != 1 else ''} "
            f"convoqué{'s' if n_invited != 1 else ''}).",
        )
        return redirect("planning:event_roster", pk=event.pk)


class InviteMusicianView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        user_id = request.POST.get("user_id")
        user = get_object_or_404(User, pk=user_id, is_musician=True)
        invited = ensure_participation_statuses()["invited"]
        EventParticipation.objects.get_or_create(
            event=event,
            user=user,
            defaults={"status": invited},
        )
        messages.success(request, f"{user} invité.")
        return redirect("planning:event_roster", pk=pk)


class InviteTitulairesView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        n = invite_titulaires_to_event(event)
        messages.success(
            request,
            f"{n} titulaire{'s' if n != 1 else ''} "
            f"convoqué{'s' if n != 1 else ''}.",
        )
        return redirect("planning:event_roster", pk=pk)


class AddEventEquipmentView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        item_id = request.POST.get("item_id")
        item = get_object_or_404(EquipmentItem, pk=item_id)
        assigned_to_id = request.POST.get("assigned_to") or None
        assigned_to = None
        if assigned_to_id:
            assigned_to = get_object_or_404(User, pk=assigned_to_id)
        EventEquipmentAssignment.objects.update_or_create(
            event=event,
            item=item,
            defaults={
                "assigned_to": assigned_to,
                "status": EventEquipmentAssignment.Status.NEEDED,
            },
        )
        messages.success(request, f"{item.name} ajouté.")
        return redirect("planning:event_roster", pk=pk)


class CreateEquipmentItemView(PlanningStaffRequiredMixin, View):
    def post(self, request):
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Nom requis.")
            return redirect("planning:admin")
        EquipmentItem.objects.create(
            name=name,
            category=(request.POST.get("category") or "").strip(),
            description=(request.POST.get("description") or "").strip(),
        )
        messages.success(request, "Matériel ajouté au catalogue.")
        return redirect("planning:admin")


class UpdateProfileSectionView(MusicianRequiredMixin, View):
    def post(self, request):
        profile = get_or_create_profile(request.user)
        section_id = request.POST.get("section_id") or None
        if section_id:
            profile.section = get_object_or_404(OrchestraSection, pk=section_id)
        else:
            profile.section = None
        profile.instrument = (request.POST.get("instrument") or "").strip()
        if request.user.is_staff or request.user.is_superuser:
            status = request.POST.get("roster_status")
            if status in MusicianProfile.RosterStatus.values:
                profile.roster_status = status
        profile.save()
        messages.success(request, "Profil mis à jour.")
        return redirect("planning:my_board")
