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
from events.weather import attach_weather
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
    attach_calendar_chat_links,
    attach_calendar_setlists,
    attach_calendar_summaries,
    cast_date_vote,
    chat_link_for_event,
    draft_proposal_for_event,
    eligible_substitutes_for,
    ensure_participation_statuses,
    get_or_create_profile,
    get_participation_for,
    invite_musician_to_event,
    invite_musicians_for_form,
    invite_titulaires_to_event,
    launch_availability_poll,
    lock_date_proposal,
    parse_invite_choice,
    propose_event,
    propose_substitute,
    respond_substitute_request,
    user_can_access_poll,
    set_participation_response,
    vote_counts_for_option,
)
from users.roles import (
    CanProposeEventMixin,
    MusicianRequiredMixin,
    user_can_access_planning,
    user_can_propose_event,
)

User = get_user_model()


def _resolve_parent_event(parent_id, *, exclude_pk=None):
    """Return Event parent or None from a POST parent_id."""
    if not parent_id:
        return None
    qs = Event.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    try:
        return qs.get(pk=int(parent_id))
    except (Event.DoesNotExist, TypeError, ValueError):
        return None


def _resolve_or_create_venue(post) -> Venue:
    """Lieu existant (venue_id) ou nouveau (venue_nom + venue_ville)."""
    mode = (post.get("venue_mode") or "existing").strip()
    if mode == "new":
        nom = (post.get("venue_nom") or "").strip()
        ville = (post.get("venue_ville") or "").strip()
        adresse = (post.get("venue_adresse") or "").strip()
        if not nom or not ville:
            raise ValueError("Nom et ville du nouveau lieu sont requis.")
        return Venue.objects.create(nom=nom, ville=ville, adresse=adresse)

    venue_id = post.get("venue_id")
    if not venue_id:
        raise ValueError("Lieu requis.")
    try:
        return Venue.objects.get(pk=int(venue_id))
    except (Venue.DoesNotExist, TypeError, ValueError) as exc:
        raise ValueError("Lieu invalide.") from exc


def _resolve_or_create_parent_event(
    post,
    *,
    venue: Venue,
    event_type: EventType,
    date_debut,
    exclude_pk=None,
):
    """Parent existant, nouveau (titre seul), ou aucun."""
    mode = (post.get("parent_mode") or "none").strip()
    if mode in ("", "none"):
        return None
    if mode == "new":
        titre = (post.get("parent_titre") or "").strip()
        if not titre:
            raise ValueError("Titre de l’événement parent requis.")
        parent = Event(
            titre=titre,
            type=event_type,
            venue=venue,
            date_debut=date_debut,
            statut=Event.Statut.TENTATIVE,
            public=False,
        )
        parent._skip_titulaire_invite = True
        parent.save()
        return parent
    return _resolve_parent_event(post.get("parent_id"), exclude_pk=exclude_pk)


def _parent_events_qs(exclude_pk=None):
    qs = Event.objects.select_related("venue").order_by("-date_debut")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs[:80]

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


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Décale (year, month) de ``delta`` mois (1–12)."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _build_rolling_calendar(
    start_year: int, start_month: int, events_by_day: dict[date, list], count: int = 12
) -> list[dict]:
    """Grille de ``count`` mois glissants à partir de start_year/start_month."""
    today = timezone.localdate()
    cal = calendar.Calendar(firstweekday=0)
    months: list[dict] = []
    for offset in range(count):
        year, month = _add_months(start_year, start_month, offset)
        weeks = []
        for week in cal.monthdayscalendar(year, month):
            days = []
            for day_num in week:
                if day_num == 0:
                    days.append(None)
                    continue
                day = date(year, month, day_num)
                day_events = events_by_day.get(day, [])
                has_confirmed = False
                has_proposal = False
                has_rehearsal = False
                has_other = False
                for e in day_events:
                    s = getattr(e, "cal_summary", None) or {}
                    if s.get("is_rehearsal"):
                        has_rehearsal = True
                    elif s.get("is_proposal"):
                        has_proposal = True
                    elif s.get("is_confirmed"):
                        has_confirmed = True
                    else:
                        has_other = True
                days.append(
                    {
                        "date": day,
                        "iso": day.isoformat(),
                        "day": day_num,
                        "events": day_events,
                        "is_today": day == today,
                        "is_past": day < today,
                        "has_confirmed": has_confirmed,
                        "has_proposal": has_proposal,
                        "has_rehearsal": has_rehearsal,
                        "has_other": has_other,
                        # Alias conservé (tests / CSS historiques « concert »).
                        "has_concert": has_confirmed,
                    }
                )
            weeks.append(days)
        months.append(
            {
                "number": month,
                "year": year,
                "name": _FRENCH_MONTHS[month],
                "label": f"{_FRENCH_MONTHS[month]} {year}",
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
            }
        )
        return context


class PlanningYearCalendarView(MusicianRequiredMixin, TemplateView):
    """Planning par défaut : 12 mois glissants à partir du mois en cours."""

    template_name = "planning/upcoming_12_months.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        try:
            year = int(self.request.GET.get("year") or today.year)
        except (TypeError, ValueError):
            year = today.year
        year = max(2000, min(2100, year))
        # Fenêtre ancrée sur le mois calendaire courant (ex. juil. → juin+1).
        start_month = today.month
        end_year, end_month = _add_months(year, start_month, 11)

        tz = timezone.get_current_timezone()
        range_start = timezone.make_aware(
            datetime.combine(date(year, start_month, 1), time.min), tz
        )
        # Dernier jour du 12ᵉ mois inclus.
        last_day = calendar.monthrange(end_year, end_month)[1]
        range_end = timezone.make_aware(
            datetime.combine(date(end_year, end_month, last_day), time.max), tz
        )
        events = list(
            Event.objects.filter(date_debut__gte=range_start, date_debut__lte=range_end)
            .select_related("type", "venue", "chat_room")
            .order_by("date_debut", "titre")
        )
        attach_calendar_summaries(events)
        attach_calendar_chat_links(events, user)
        attach_calendar_setlists(events)
        attach_weather(events, concerts_only=True)
        events_by_day: dict[date, list] = defaultdict(list)
        for event in events:
            events_by_day[timezone.localtime(event.date_debut).date()].append(event)

        is_staff = user.is_staff or user.is_superuser
        can_propose = user_can_propose_event(user)
        need_form_data = can_propose
        start_label = f"{_FRENCH_MONTHS[start_month]} {year}"
        end_label = f"{_FRENCH_MONTHS[end_month]} {end_year}"
        context.update(
            {
                "calendar_year": year,
                "prev_year": year - 1,
                "next_year": year + 1,
                "start_month": start_month,
                "range_label": f"{start_label} — {end_label}",
                "weekday_labels": _WEEKDAY_LABELS,
                "months": _build_rolling_calendar(
                    year, start_month, events_by_day, count=12
                ),
                "is_planning_staff": is_staff,
                "can_propose_event": can_propose,
                "venues": (
                    Venue.objects.all().order_by("ville", "nom") if need_form_data else []
                ),
                "event_types": (
                    EventType.objects.all().order_by("nom") if need_form_data else []
                ),
                "parent_events": _parent_events_qs() if is_staff else [],
            }
        )
        return context


# Alias conservé pour les URLs / tests existants.
PlanningUpcomingView = PlanningYearCalendarView


def _calendar_url(day_raw: str) -> str:
    """URL du calendrier glissant qui contient ce jour (+ ancre day)."""
    try:
        day = date.fromisoformat(day_raw)
    except ValueError:
        return reverse("planning:dashboard")
    today = timezone.localdate()
    # Fenêtre ancrée sur today.month : si le jour est avant ce mois dans son année,
    # il appartient à la fenêtre démarrée l’année précédente.
    if day.month >= today.month:
        window_year = day.year
    else:
        window_year = day.year - 1
    return (
        f"{reverse('planning:dashboard')}?year={window_year}&day={day.isoformat()}"
    )


class ProposeEventView(CanProposeEventMixin, View):
    """Proposition d’événement (musicien ou adhérent) → salon staff + sondage brouillon."""

    def get(self, request):
        # Page dédiée (adhérents hors planning calendrier).
        if user_can_access_planning(request.user):
            return redirect("planning:dashboard")
        from django.shortcuts import render

        return render(
            request,
            "planning/propose_event.html",
            {
                "venues": Venue.objects.all().order_by("ville", "nom"),
                "event_types": EventType.objects.all().order_by("nom"),
                "preset_date": (request.GET.get("date") or "").strip(),
            },
        )

    def post(self, request):
        titre = (request.POST.get("titre") or "").strip()
        type_id = request.POST.get("type_id")
        day_raw = (request.POST.get("date") or "").strip()
        time_raw = (request.POST.get("time") or "20:00").strip() or "20:00"

        def _fail(msg: str):
            messages.error(request, msg)
            if user_can_access_planning(request.user):
                return redirect(_calendar_url(day_raw))
            return redirect("planning:propose_event")

        if not titre or not type_id or not day_raw:
            return _fail("Titre, date et type sont requis.")

        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            return _fail("Date invalide.")

        try:
            hour, minute = (int(x) for x in time_raw.split(":")[:2])
            starts = timezone.make_aware(datetime.combine(day, time(hour, minute)))
        except (ValueError, TypeError):
            return _fail("Heure invalide.")

        event_type = get_object_or_404(EventType, pk=type_id)
        try:
            venue = _resolve_or_create_venue(request.POST)
            parent = None
            if request.user.is_staff or request.user.is_superuser:
                parent = _resolve_or_create_parent_event(
                    request.POST,
                    venue=venue,
                    event_type=event_type,
                    date_debut=starts,
                )
        except ValueError as exc:
            return _fail(str(exc))

        public = False

        event, _proposal = propose_event(
            proposer=request.user,
            titre=titre,
            event_type=event_type,
            venue=venue,
            date_debut=starts,
            description=(request.POST.get("description") or "").strip(),
            organisme=(request.POST.get("organisme") or "").strip(),
            parent=parent,
            public=public,
            contact_nom=(request.POST.get("contact_nom") or "").strip(),
            contact_telephone=(request.POST.get("contact_telephone") or "").strip(),
            contact_email=(request.POST.get("contact_email") or "").strip(),
        )

        if request.user.is_staff or request.user.is_superuser:
            messages.success(
                request,
                f"Événement « {event.titre} » créé — salon staff ouvert. "
                f"Invitez des musiciens puis lancez le sondage de disponibilité.",
            )
            return redirect("planning:event_roster", pk=event.pk)

        messages.success(
            request,
            f"Proposition « {event.titre} » envoyée. "
            f"Le staff ouvrira le salon et lancera le sondage de disponibilité.",
        )
        if user_can_access_planning(request.user):
            return redirect("planning:event_detail", pk=event.pk)
        return redirect("account_member_area")


class CreateEventView(PlanningStaffRequiredMixin, View):
    """Création staff (calendrier) — même flux que propose (salon staff + sondage)."""

    def post(self, request):
        # Délègue au même traitement que ProposeEventView.
        return ProposeEventView.as_view()(request)

class EventDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/event_detail.html"

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(Event.objects.select_related("type"), pk=kwargs["pk"])
        if event.is_rehearsal:
            return redirect("repetitions:detail", pk=event.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(
            Event.objects.select_related("venue", "type", "parent", "chat_room"),
            pk=kwargs["pk"],
        )
        attach_weather([event], concerts_only=True)
        user = self.request.user
        participation = get_participation_for(event, user)
        chat_link = chat_link_for_event(event, user)

        parts = (
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__last_name",
                "user__first_name",
            )
        )
        by_section: dict[str, list] = defaultdict(list)
        section_order: dict[str, int] = {}
        counts = {
            "confirmed": 0,
            "invited": 0,
            "maybe": 0,
            "declined": 0,
            "replacement_needed": 0,
        }
        for p in parts:
            section = p.section_for_roster()
            section_name = section.name if section else "Sans pupitre"
            by_section[section_name].append(p)
            if section_name not in section_order:
                section_order[section_name] = (
                    section.sort_order if section else 999
                )
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

        is_staff = user.is_staff or user.is_superuser
        setlist = _active_setlist_for_event(event)
        attachable_setlists = None
        if is_staff and not setlist:
            from repertoire.models import Setlist

            attachable_setlists = list(
                Setlist.objects.select_related("event")
                .order_by("-updated_at")[:80]
            )

        context.update(
            {
                "event": event,
                "participation": participation,
                "by_section": {
                    name: by_section[name]
                    for name in sorted(
                        by_section.keys(),
                        key=lambda n: (section_order.get(n, 999), n),
                    )
                },
                "counts": counts,
                "eligible_subs": eligible,
                "my_sub_requests": my_sub_requests,
                "gear": gear,
                "chat_link": chat_link,
                "is_planning_staff": is_staff,
                "setlist": setlist,
                "attachable_setlists": attachable_setlists,
            }
        )
        return context


def _active_setlist_for_event(event):
    from repertoire.models import Setlist

    return (
        Setlist.objects.filter(event=event, is_active=True)
        .prefetch_related("items__piece")
        .order_by("-updated_at")
        .first()
    )


class PollDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/poll_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        proposal = get_object_or_404(
            DateProposal.objects.select_related(
                "linked_event",
                "linked_event__venue",
                "linked_event__type",
                "linked_event__chat_room",
            ).prefetch_related(
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
        is_staff = user.is_staff or user.is_superuser
        # Brouillon : visible staff uniquement (pas encore autorisé).
        if proposal.is_draft and not is_staff:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Sondage pas encore lancé par le staff.")
        if not user_can_access_poll(user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Vous n’êtes pas concerné par ce sondage.")
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
        event = proposal.linked_event
        context.update(
            {
                "proposal": proposal,
                "event": event,
                "options_data": options_data,
                "is_planning_staff": is_staff,
            }
        )

        # Salon embarqué si événement lié et accès (membre ou staff).
        if event:
            from chat.services import (
                active_membership,
                build_room_embed_context,
                ensure_event_room,
            )

            room = ensure_event_room(event)
            membership = active_membership(room, user)
            if membership is not None or is_staff:
                embed = build_room_embed_context(self.request, room)
                embed["embedded"] = True
                embed["show_chat_chrome"] = False
                # Sur la page sondage, open_proposal = ce sondage s'il est ouvert.
                if proposal.is_open:
                    embed["open_proposal"] = proposal
                    embed["lock_options"] = [
                        item["option"] for item in options_data
                    ]
                context.update(embed)
            else:
                context["room"] = None
        else:
            context["room"] = None

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
        draft_polls = DateProposal.objects.filter(
            status=DateProposal.Status.DRAFT
        ).annotate(n_options=Count("options"))
        sections = OrchestraSection.objects.filter(is_active=True)
        equipment = EquipmentItem.objects.filter(is_active=True)
        context.update(
            {
                "events": events,
                "open_polls": open_polls,
                "draft_polls": draft_polls,
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
            Event.objects.select_related("venue", "type", "parent"),
            pk=kwargs["pk"],
        )
        parts = (
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__last_name",
                "user__first_name",
            )
        )
        by_section: dict[str, list] = defaultdict(list)
        section_order: dict[str, int] = {}
        for p in parts:
            section = p.section_for_roster()
            name = section.name if section else "Sans pupitre"
            by_section[name].append(p)
            if name not in section_order:
                section_order[name] = section.sort_order if section else 999

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
                "by_section": {
                    name: by_section[name]
                    for name in sorted(
                        by_section.keys(),
                        key=lambda n: (section_order.get(n, 999), n),
                    )
                },
                "gear": gear,
                "equipment_catalog": EquipmentItem.objects.filter(is_active=True),
                "musicians": musicians,
                "invite_musicians": invite_musicians_for_form(musicians),
                "parent_events": _parent_events_qs(exclude_pk=event.pk),
                "draft_proposal": draft_proposal_for_event(event),
            }
        )
        return context


class UpdateEventPublicationView(PlanningStaffRequiredMixin, View):
    """Rendre un événement public / privé et renseigner organisme + parent."""

    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        event.public = request.POST.get("public") == "on"
        event.organisme = (request.POST.get("organisme") or "").strip()
        event.parent = _resolve_parent_event(
            request.POST.get("parent_id"), exclude_pk=event.pk
        )
        event.save(update_fields=["public", "organisme", "parent"])
        if event.public:
            messages.success(
                request,
                f"« {event.titre} » est maintenant visible sur le site public.",
            )
        else:
            messages.success(
                request,
                f"« {event.titre} » n’apparaît plus sur le site public.",
            )
        return redirect("planning:event_roster", pk=event.pk)


class CreatePollView(PlanningStaffRequiredMixin, View):
    def post(self, request):
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Titre requis.")
            return redirect("planning:admin")
        description = (request.POST.get("description") or "").strip()
        # Brouillon : le staff doit lancer explicitement le sondage.
        proposal = DateProposal.objects.create(
            title=title,
            description=description,
            created_by=request.user,
            status=DateProposal.Status.DRAFT,
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
        messages.success(
            request,
            "Sondage créé en brouillon — lancez-le pour notifier les musiciens.",
        )
        return redirect("planning:poll_detail", pk=proposal.pk)


class LaunchPollView(PlanningStaffRequiredMixin, View):
    """Autorise / lance le sondage de disponibilité (+ highlight chat + notification)."""

    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        try:
            launch_availability_poll(proposal, launched_by=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)
        messages.success(
            request,
            "Sondage lancé — mis en évidence dans le salon, "
            "notifications envoyées aux invités.",
        )
        return redirect("planning:poll_detail", pk=pk)


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

        # Sondage déjà lié à un événement : valider la date sans créer d’événement.
        if proposal.linked_event_id:
            event = proposal.linked_event
            event.date_debut = option.starts_at
            event.date_fin = option.ends_at
            event.statut = Event.Statut.CONFIRME
            event.save(update_fields=["date_debut", "date_fin", "statut"])
            lock_date_proposal(proposal, option, event=event)
            messages.success(
                request,
                f"Date validée — « {event.titre} » confirmé "
                f"({option.starts_at.strftime('%d/%m/%Y %H:%M')}).",
            )
            return redirect("planning:poll_detail", pk=pk)

        type_id = request.POST.get("type_id")
        if not type_id:
            messages.error(request, "Type requis pour créer l’événement.")
            return redirect("planning:poll_detail", pk=pk)

        event_type = get_object_or_404(EventType, pk=type_id)
        try:
            venue = _resolve_or_create_venue(request.POST)
            parent = _resolve_or_create_parent_event(
                request.POST,
                venue=venue,
                event_type=event_type,
                date_debut=option.starts_at,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)

        public = False
        organisme = (request.POST.get("organisme") or "").strip()
        contact_nom = (request.POST.get("contact_nom") or "").strip()
        contact_telephone = (request.POST.get("contact_telephone") or "").strip()
        contact_email = (request.POST.get("contact_email") or "").strip()
        event = Event.objects.create(
            titre=proposal.title,
            type=event_type,
            venue=venue,
            date_debut=option.starts_at,
            date_fin=option.ends_at,
            description=proposal.description,
            statut=Event.Statut.TENTATIVE,
            public=public,
            parent=parent,
            organisme=organisme,
            contact_nom=contact_nom,
            contact_telephone=contact_telephone,
            contact_email=contact_email,
        )
        # Les titulaires ne sont plus convoqués automatiquement.
        lock_date_proposal(proposal, option, event=event)
        messages.success(
            request,
            f"Date verrouillée — événement « {event.titre} » créé. "
            f"Invitez les musiciens depuis le roster ou le salon.",
        )
        return redirect("planning:event_roster", pk=event.pk)


class InviteMusicianView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        raw = request.POST.get("invite_slot") or request.POST.get("user_id") or ""
        user_id, poste = parse_invite_choice(raw)
        if user_id is None:
            # Compat : ancien formulaire user_id + poste séparés
            try:
                user_id = int(request.POST.get("user_id") or 0) or None
            except (TypeError, ValueError):
                user_id = None
            poste = (request.POST.get("poste") or "").strip()
        if user_id is None:
            messages.error(request, "Musicien requis.")
            return redirect("planning:event_roster", pk=pk)
        user = get_object_or_404(User, pk=user_id, is_musician=True, is_active=True)
        try:
            _part, created = invite_musician_to_event(
                event, user, poste=poste, send_notification=True
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            next_url = request.POST.get("next") or ""
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect("planning:event_roster", pk=pk)
        if created:
            name = user.get_full_name() or user.username
            if _part.poste:
                messages.success(
                    request,
                    f"{name} invité · {_part.poste_label} (notification envoyée).",
                )
            else:
                messages.success(
                    request,
                    f"{name} invité au salon (notification envoyée).",
                )
        else:
            messages.info(request, f"{user} était déjà invité.")
        next_url = request.POST.get("next") or ""
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("planning:event_roster", pk=pk)


class InviteTitulairesView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        n = invite_titulaires_to_event(event, send_notification=True)
        messages.success(
            request,
            f"{n} titulaire{'s' if n != 1 else ''} "
            f"convoqué{'s' if n != 1 else ''} (notifications envoyées).",
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
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "Modification réservée au staff.")
            return redirect("planning:my_board")
        profile = get_or_create_profile(request.user)
        tit = (request.POST.get("poste_titulaire") or "").strip()
        rem_list = [
            (request.POST.get(field) or "").strip()
            for field in MusicianProfile.POSTE_REMPLACANT_FIELDS
        ]
        rem_filled = [p for p in rem_list if p]
        if len(set(rem_filled)) != len(rem_filled):
            messages.error(
                request,
                "Les postes remplaçants doivent être distincts.",
            )
            return redirect("planning:my_board")
        if tit and tit in rem_filled:
            messages.error(
                request,
                "Poste titulaire et remplaçants doivent être différents.",
            )
            return redirect("planning:my_board")
        profile.poste_titulaire = (
            tit if tit in MusicianProfile.Poste.values else ""
        )
        profile.set_postes_remplacant(rem_list)
        profile.save()  # pupitre déduit du poste titulaire
        messages.success(request, "Profil mis à jour.")
        return redirect("planning:my_board")


class AdminMusiciansView(PlanningStaffRequiredMixin, TemplateView):
    template_name = "planning/admin_musicians.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Guérison : flag is_musician coché dans l’admin Django sans profil.
        for user in User.objects.filter(
            is_musician=True, musician_profile__isnull=True
        ):
            get_or_create_profile(user)
        profiles = (
            MusicianProfile.objects.select_related("user", "section")
            .filter(user__is_musician=True)
            .order_by("user__last_name", "user__first_name")
        )
        context["profiles"] = profiles
        return context


class AdminMusicianEditView(PlanningStaffRequiredMixin, View):
    template_name = "planning/admin_musician_edit.html"

    def get(self, request, pk=None):
        from planning.forms import MusicianAdminForm

        profile = None
        if pk is not None:
            profile = get_object_or_404(
                MusicianProfile.objects.select_related("user"),
                pk=pk,
            )
        form = MusicianAdminForm(profile=profile)
        return self._render(request, form, profile)

    def post(self, request, pk=None):
        from planning.forms import MusicianAdminForm

        profile = None
        if pk is not None:
            profile = get_object_or_404(
                MusicianProfile.objects.select_related("user"),
                pk=pk,
            )
        form = MusicianAdminForm(request.POST, profile=profile)
        if form.is_valid():
            saved = form.save()
            messages.success(
                request,
                f"Musicien « {saved.user} » enregistré."
                + (
                    " Mot de passe à définir via Django admin ou réinitialisation."
                    if pk is None
                    else ""
                ),
            )
            return redirect("planning:admin_musicians")
        return self._render(request, form, profile)

    def _render(self, request, form, profile):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"form": form, "profile": profile},
        )


class AdminMusicianRemoveView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk):
        profile = get_object_or_404(
            MusicianProfile.objects.select_related("user"),
            pk=pk,
        )
        user = profile.user
        user.is_musician = False
        user.save(update_fields=["is_musician"])
        from users.roles import sync_user_groups

        sync_user_groups(user)
        messages.success(
            request,
            f"{user} n’est plus marqué comme musicien.",
        )
        return redirect("planning:admin_musicians")
