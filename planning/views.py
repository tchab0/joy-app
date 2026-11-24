from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import AccessMixin
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views import View
from django.views.generic import TemplateView

from core.safe_redirect import is_safe_local_path
from events.models import Event, EventType, Organisme, Venue
from events.organisme import remember_organisme
from events.weather import attach_weather
from planning.models import (
    DateOption,
    DateProposal,
    DateVote,
    EquipmentItem,
    EventEquipmentAssignment,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    SubstituteRequest,
)
from planning.services import (
    attach_calendar_chat_links,
    attach_calendar_participations,
    attach_calendar_recent_messages,
    attach_calendar_setlists,
    attach_calendar_rehearsal_plans,
    attach_calendar_summaries,
    attach_calendar_roadmaps,
    event_calendar_presence_state,
    attach_open_poll_info_to_events,
    attach_roster_substitutes,
    cast_date_vote,
    chat_link_for_event,
    draft_proposal_for_event,
    open_proposal_for_event,
    eligible_substitutes_for,
    ensure_default_equipment,
    ensure_open_participation,
    ensure_participation_statuses,
    EQUIPMENT_CATEGORIES,
    format_poll_vote_counts,
    poll_participation_lead,
    poll_room_summary,
    get_or_create_equipment_item,
    get_or_create_profile,
    get_participation_for,
    get_or_create_roadmap,
    get_roadmap,
    board_rows_for_user,
    invite_musician_to_event,
    invite_musicians_for_form,
    invite_titulaires_to_event,
    launch_availability_poll,
    update_poll_meta,
    close_poll,
    cancel_poll,
    cancel_event,
    user_can_view_planning_event,
    notify_poll_non_responders,
    lock_date_proposal,
    notify_roadmap,
    open_poll_calendar_markers_for_user,
    parse_invite_choice,
    parse_poll_audience,
    poll_audience_label,
    poll_launch_success_message,
    poll_recipient_count,
    propose_event,
    create_confirmed_event,
    propose_substitute,
    respond_substitute_request,
    roster_by_stage,
    suggest_defaults,
    suggest_event_equipment,
    sync_known_fields,
    user_can_access_poll,
    user_has_answered_poll,
    sibling_polls_for_user,
    poll_embed_room,
    user_can_view_roadmap,
    set_participation_response,
    user_can_edit_poll_deadline,
    user_can_edit_poll_options,
    update_poll_options,
    vote_counts_for_option,
    build_calendar_feed,
    build_event_ics,
    event_allows_personal_calendar,
    ics_filename,
    mine_feed_events,
    orchestra_feed_events,
    roadmaps_for_events,
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


def _parse_venue_coords(post) -> tuple[Decimal | None, Decimal | None]:
    """Latitude / longitude optionnelles depuis le formulaire (carte OSM)."""
    lat_raw = (post.get("venue_latitude") or "").strip()
    lng_raw = (post.get("venue_longitude") or "").strip()
    if not lat_raw or not lng_raw:
        return None, None
    try:
        lat = Decimal(lat_raw)
        lng = Decimal(lng_raw)
    except (InvalidOperation, ValueError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def _apply_venue_coords(venue: Venue, lat, lng) -> Venue:
    """Met à jour les coordonnées du lieu si fournies."""
    if lat is None or lng is None:
        return venue
    if venue.latitude == lat and venue.longitude == lng:
        return venue
    venue.latitude = lat
    venue.longitude = lng
    venue.save(update_fields=["latitude", "longitude"])
    return venue


def _resolve_or_create_venue(post) -> Venue:
    """Lieu existant (venue_id) ou nouveau (venue_nom + venue_ville + carte)."""
    mode = (post.get("venue_mode") or "existing").strip()
    lat, lng = _parse_venue_coords(post)
    if mode == "new":
        nom = (post.get("venue_nom") or "").strip()
        ville = (post.get("venue_ville") or "").strip()
        adresse = (post.get("venue_adresse") or "").strip()
        if not ville:
            raise ValueError("La ville du lieu est obligatoire.")
        if not nom:
            raise ValueError("Le nom du lieu est obligatoire.")
        return Venue.objects.create(
            nom=nom,
            ville=ville,
            adresse=adresse,
            latitude=lat,
            longitude=lng,
        )

    venue_id = post.get("venue_id")
    if not venue_id:
        raise ValueError("Lieu requis.")
    try:
        venue = Venue.objects.get(pk=int(venue_id))
    except (Venue.DoesNotExist, TypeError, ValueError) as exc:
        raise ValueError("Lieu invalide.") from exc
    return _apply_venue_coords(venue, lat, lng)


def _remember_organisme(name: str, url_site: str = "") -> str:
    return remember_organisme(name, url_site)


def _organismes_qs():
    return Organisme.objects.all().order_by("nom")


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
    start_year: int,
    start_month: int,
    events_by_day: dict[date, list],
    count: int = 12,
    *,
    user=None,
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
                is_past = day < today
                day_events = events_by_day.get(day, [])
                has_confirmed = False
                has_proposal = False
                has_rehearsal = False
                has_other = False
                presence_items = []
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
                    p_state = event_calendar_presence_state(
                        e, user=user, is_past=is_past
                    )
                    e.cal_presence = p_state
                    presence_items.append(p_state)
                is_absent_day = bool(presence_items) and all(
                    item["is_absent"] for item in presence_items
                )
                presence_status = (
                    ("absent" if is_absent_day else "present")
                    if presence_items
                    else ""
                )
                needs_response = any(
                    item["needs_response"] for item in presence_items
                )
                days.append(
                    {
                        "date": day,
                        "iso": day.isoformat(),
                        "day": day_num,
                        "events": day_events,
                        "is_today": day == today,
                        "is_past": is_past,
                        "has_confirmed": has_confirmed,
                        "has_proposal": has_proposal,
                        "has_rehearsal": has_rehearsal,
                        "has_other": has_other,
                        # Alias conservé (tests / CSS historiques « concert »).
                        "has_concert": has_confirmed,
                        "presence_status": presence_status,
                        "is_absent": is_absent_day,
                        "needs_response": needs_response,
                        "presence_items": presence_items,
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

        # Toutes les dates à venir (confirmées ou non) — positionnement libre.
        all_rows = board_rows_for_user(user, limit=40)
        pending = [
            row
            for row in all_rows
            if (not row.event.is_rehearsal)
            and row.status.code in ("invited", "maybe")
        ]
        pending_event_ids = {row.event.pk for row in pending}
        # « Prochaines dates » = le reste (pas de doublon avec « À répondre »),
        # avec au plus 2 répétitions (les plus proches).
        upcoming = []
        rehearsals_kept = 0
        for row in all_rows:
            if row.event.pk in pending_event_ids:
                continue
            if row.event.is_rehearsal:
                if rehearsals_kept >= 2:
                    continue
                rehearsals_kept += 1
            upcoming.append(row)

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
            .exclude(event__statut=Event.Statut.ANNULE)
            .select_related("event", "item")
            .order_by("event__date_debut")[:15]
        )

        # Sondages de dates d'événements encore ouverts (à voter ou déjà votés).
        open_polls_qs = (
            DateProposal.objects.filter(status=DateProposal.Status.OPEN)
            .exclude(source_room__isnull=False, linked_event__isnull=True)
            .select_related("linked_event", "linked_event__venue")
            .prefetch_related("options__votes")
            .order_by("-launched_at", "-created_at")
        )
        open_date_polls = []
        for poll in open_polls_qs:
            if not user_can_access_poll(user, poll):
                continue
            poll.user_answered = user_has_answered_poll(user, poll)
            open_date_polls.append(poll)

        context.update(
            {
                "open_date_polls": open_date_polls,
                "pending": pending,
                "upcoming": upcoming,
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
        raw_events = list(
            Event.objects.filter(date_debut__gte=range_start, date_debut__lte=range_end)
            .exclude(statut=Event.Statut.ANNULE)
            .select_related("type", "venue", "chat_room", "proposed_by")
            .prefetch_related(
                Prefetch(
                    "from_proposals",
                    queryset=DateProposal.objects.select_related("created_by"),
                )
            )
            .order_by("date_debut", "titre")
        )
        events = [
            e for e in raw_events if user_can_view_planning_event(user, e)
        ]
        attach_calendar_summaries(events)
        attach_open_poll_info_to_events(events, user)
        attach_calendar_chat_links(events, user)
        attach_calendar_participations(events, user)
        attach_calendar_recent_messages(events, user)
        attach_calendar_setlists(events)
        attach_calendar_rehearsal_plans(events)
        attach_calendar_roadmaps(events)
        events_by_day: dict[date, list] = defaultdict(list)
        for event in events:
            events_by_day[timezone.localtime(event.date_debut).date()].append(event)

        # Options des sondages OPEN → propositions calendrier (sans Event).
        for marker in open_poll_calendar_markers_for_user(
            user, range_start=range_start, range_end=range_end
        ):
            events_by_day[timezone.localtime(marker.date_debut).date()].append(marker)

        is_staff = user.is_staff or user.is_superuser
        can_propose = user_can_propose_event(user)
        need_form_data = can_propose
        start_label = f"{_FRENCH_MONTHS[start_month]} {year}"
        end_label = f"{_FRENCH_MONTHS[end_month]} {end_year}"
        months = _build_rolling_calendar(
            year, start_month, events_by_day, count=12, user=user
        )
        calendar_presence_map = {
            day["iso"]: day["presence_items"]
            for month in months
            for week in month["weeks"]
            for day in week
            if day and day["presence_items"]
        }
        context.update(
            {
                "calendar_year": year,
                "prev_year": year - 1,
                "next_year": year + 1,
                "start_month": start_month,
                "range_label": f"{start_label} — {end_label}",
                "weekday_labels": _WEEKDAY_LABELS,
                "months": months,
                "calendar_presence_map": calendar_presence_map,
                "is_planning_staff": is_staff,
                "can_propose_event": can_propose,
                "venues": (
                    Venue.objects.all().order_by("ville", "nom") if need_form_data else []
                ),
                "event_types": (
                    EventType.objects.all().order_by("nom") if need_form_data else []
                ),
                "organismes": _organismes_qs() if need_form_data else [],
                "parent_events": _parent_events_qs() if is_staff else [],
            }
        )
        return context


# Alias conservé pour les URLs / tests existants.
PlanningUpcomingView = PlanningYearCalendarView


def _ics_http_response(body: str, *, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "private, max-age=300"
    return response


def _user_for_calendar_token(token: str):
    token = (token or "").strip()
    if not token or len(token) < 16:
        return None
    try:
        user = User.objects.get(calendar_feed_token=token, is_active=True)
    except User.DoesNotExist:
        return None
    if not user_can_access_planning(user):
        return None
    return user


class CalendarFeedOrchestraView(View):
    """Flux ICS orchestre (token secret, sans session)."""

    def get(self, request, token: str):
        if _user_for_calendar_token(token) is None:
            return HttpResponse(status=404)
        events = orchestra_feed_events()
        body = build_calendar_feed(
            events,
            name="JOY — Orchestre",
            roadmaps=roadmaps_for_events(events),
        )
        return _ics_http_response(body, filename="joy-orchestre.ics")


class CalendarFeedMineView(View):
    """Flux ICS « mes dates » (token secret, sans session)."""

    def get(self, request, token: str):
        user = _user_for_calendar_token(token)
        if user is None:
            return HttpResponse(status=404)
        events, status_map = mine_feed_events(user)
        body = build_calendar_feed(
            events,
            name="JOY — Mes dates",
            event_status_fn=lambda ev: status_map.get(ev.pk, "TENTATIVE"),
            roadmaps=roadmaps_for_events(events),
        )
        return _ics_http_response(body, filename="joy-mes-dates.ics")


class EventIcsView(MusicianRequiredMixin, View):
    """Téléchargement .ics d’un événement confirmé (hors répétition)."""

    def get(self, request, pk: int):
        event = get_object_or_404(
            Event.objects.select_related("type", "venue"), pk=pk
        )
        if not event_allows_personal_calendar(event):
            return HttpResponse(status=404)
        from planning.services import get_roadmap

        roadmap = get_roadmap(event)
        try:
            body = build_event_ics(event, roadmap=roadmap)
        except ValueError:
            return HttpResponse(status=404)
        return _ics_http_response(body, filename=ics_filename(event))


class CalendarWeatherView(MusicianRequiredMixin, View):
    """Hydrate les prévisions après le premier rendu du calendrier."""

    def get(self, request):
        raw_ids = (request.GET.get("ids") or "").split(",")
        event_ids: list[int] = []
        for raw_id in raw_ids[:200]:
            try:
                event_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if not event_ids:
            return JsonResponse({"weather": {}})

        events = list(
            Event.objects.filter(pk__in=event_ids)
            .select_related("venue", "type")
            .order_by("pk")
        )
        attach_weather(events, concerts_only=True)
        return JsonResponse(
            {
                "weather": {
                    str(event.pk): render_to_string(
                        "includes/_weather.html",
                        {"weather": event.weather, "compact": 1},
                        request=request,
                    )
                    for event in events
                    if event.weather
                }
            }
        )


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
                "organismes": _organismes_qs(),
                "preset_date": (request.GET.get("date") or "").strip(),
            },
        )

    def post(self, request):
        titre = (request.POST.get("titre") or "").strip()
        type_id = request.POST.get("type_id")
        day_raw = (request.POST.get("date") or "").strip()
        time_raw = (request.POST.get("time") or "20:00").strip() or "20:00"
        date_label = (request.POST.get("date_label") or "").strip()

        def _fail(msg: str):
            messages.error(request, msg)
            if user_can_access_planning(request.user):
                return redirect(_calendar_url(day_raw))
            return redirect("planning:propose_event")

        if not titre or not type_id or not day_raw:
            return _fail("Titre, date et type sont requis.")

        is_staff_user = bool(request.user.is_staff or request.user.is_superuser)
        creation_mode = (request.POST.get("creation_mode") or "").strip().lower()
        confirmed_direct = is_staff_user and creation_mode == "confirmed"

        deadline = None
        if not confirmed_direct:
            deadline_raw = (request.POST.get("deadline") or "").strip()
            deadline = parse_date(deadline_raw) if deadline_raw else None
            if deadline is None and not is_staff_user:
                return _fail("Indiquez une date limite de réponse.")

        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            return _fail("Date invalide.")

        try:
            hour, minute = (int(x) for x in time_raw.split(":")[:2])
            starts = timezone.make_aware(datetime.combine(day, time(hour, minute)))
        except (ValueError, TypeError):
            return _fail("Heure invalide.")

        extra_options: list[tuple] = []
        if not confirmed_direct:
            for i in range(20):
                ex_day_raw = (request.POST.get(f"extra_date_{i}") or "").strip()
                if not ex_day_raw:
                    continue
                ex_time_raw = (
                    request.POST.get(f"extra_time_{i}") or "20:00"
                ).strip() or "20:00"
                ex_label = (request.POST.get(f"extra_label_{i}") or "").strip()
                try:
                    ex_day = date.fromisoformat(ex_day_raw)
                except ValueError:
                    return _fail(f"Date supplémentaire #{i + 2} invalide.")
                try:
                    ex_h, ex_m = (int(x) for x in ex_time_raw.split(":")[:2])
                    ex_starts = timezone.make_aware(
                        datetime.combine(ex_day, time(ex_h, ex_m))
                    )
                except (ValueError, TypeError):
                    return _fail(f"Heure supplémentaire #{i + 2} invalide.")
                extra_options.append((ex_starts, None, ex_label))

        event_type = get_object_or_404(EventType, pk=type_id)
        try:
            venue = _resolve_or_create_venue(request.POST)
            parent = None
            if is_staff_user:
                parent = _resolve_or_create_parent_event(
                    request.POST,
                    venue=venue,
                    event_type=event_type,
                    date_debut=starts,
                )
        except ValueError as exc:
            return _fail(str(exc))

        from core.ratelimit import claim_once

        dedupe_key = (
            f"{request.user.pk}:{creation_mode}:{titre.casefold()}:{starts.isoformat()}"
        )
        if not claim_once("propose_event", dedupe_key, 45):
            existing = (
                Event.objects.filter(
                    titre=titre,
                    proposed_by=request.user,
                    date_debut=starts,
                )
                .exclude(statut=Event.Statut.ANNULE)
                .order_by("-id")
                .first()
            )
            messages.warning(
                request,
                "Cette proposition vient d’être enregistrée (double envoi évité).",
            )
            if existing and is_staff_user:
                return redirect("planning:event_roster", pk=existing.pk)
            if existing and user_can_access_planning(request.user):
                return redirect("planning:event_detail", pk=existing.pk)
            if user_can_access_planning(request.user):
                return redirect(_calendar_url(day_raw))
            return redirect("account_member_area")

        organisme = _remember_organisme(
            request.POST.get("organisme") or "",
            request.POST.get("organisme_url") or "",
        )
        description = (request.POST.get("description") or "").strip()
        contact_nom = (request.POST.get("contact_nom") or "").strip()
        contact_telephone = (request.POST.get("contact_telephone") or "").strip()
        contact_email = (request.POST.get("contact_email") or "").strip()

        if confirmed_direct:
            event = create_confirmed_event(
                creator=request.user,
                titre=titre,
                event_type=event_type,
                venue=venue,
                date_debut=starts,
                description=description,
                organisme=organisme,
                parent=parent,
                contact_nom=contact_nom,
                contact_telephone=contact_telephone,
                contact_email=contact_email,
            )
            messages.success(
                request,
                f"Événement « {event.titre} » confirmé "
                f"({starts.strftime('%d/%m/%Y %H:%M')}). "
                f"Convoquez maintenant l’effectif depuis cette page.",
            )
            return redirect("planning:event_roster", pk=event.pk)

        poll_audience = parse_poll_audience(
            request.POST.get("audience"),
            default=DateProposal.Audience.ALL,
        )
        event, proposal = propose_event(
            proposer=request.user,
            titre=titre,
            event_type=event_type,
            venue=venue,
            date_debut=starts,
            date_label=date_label,
            extra_options=extra_options,
            description=description,
            organisme=organisme,
            parent=parent,
            public=False,
            contact_nom=contact_nom,
            contact_telephone=contact_telephone,
            contact_email=contact_email,
            deadline=deadline,
            audience=poll_audience,
        )

        keep_draft = str(request.POST.get("keep_draft") or "").strip().lower() in (
            "1",
            "on",
            "true",
            "yes",
        )
        if is_staff_user:
            if creation_mode == "poll":
                launch_now = not keep_draft
            elif creation_mode == "draft":
                launch_now = False
            else:
                launch_now = str(
                    request.POST.get("launch_poll") or ""
                ).strip().lower() in ("1", "on", "true", "yes")
        else:
            launch_now = False

        if launch_now:
            try:
                launch_availability_poll(
                    proposal,
                    launched_by=request.user,
                    audience=poll_audience,
                    require_recipients=True,
                )
            except ValueError as exc:
                messages.warning(
                    request,
                    f"Événement créé, mais le sondage n’a pas pu être lancé : {exc}",
                )
                return redirect("planning:event_roster", pk=event.pk)

        if is_staff_user:
            if launch_now:
                sent = poll_recipient_count(proposal)
                messages.success(
                    request,
                    f"Événement « {event.titre} » créé — "
                    f"{poll_launch_success_message(proposal, sent=sent)}",
                )
            else:
                messages.success(
                    request,
                    f"Proposition « {event.titre} » enregistrée en brouillon staff "
                    f"(invisible de l’orchestre tant que vous ne lancez pas le sondage).",
                )
            if launch_now or creation_mode in ("poll", "draft"):
                return redirect("planning:poll_detail", pk=proposal.pk)
            return redirect("planning:event_roster", pk=event.pk)

        messages.success(
            request,
            f"Proposition « {event.titre} » envoyée au staff. "
            f"Elle apparaîtra au calendrier de l’orchestre dès que le staff ouvrira le sondage.",
        )
        if user_can_access_planning(request.user):
            return redirect("planning:poll_detail", pk=proposal.pk)
        return redirect("account_member_area")


class CreateEventView(PlanningStaffRequiredMixin, View):
    """Création staff (calendrier) — même flux que propose (salon staff + sondage)."""

    def post(self, request):
        # Délègue au même traitement que ProposeEventView.
        return ProposeEventView.as_view()(request)

class EventDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "planning/event_detail.html"

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(
            Event.objects.select_related("type", "proposed_by"), pk=kwargs["pk"]
        )
        if event.is_rehearsal:
            return redirect("repetitions:detail", pk=event.pk)
        res = super().dispatch(request, *args, **kwargs)
        return res

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(
            Event.objects.select_related(
                "venue", "type", "parent", "chat_room", "proposed_by"
            ),
            pk=kwargs["pk"],
        )
        user = self.request.user
        if (
            event.statut == Event.Statut.TENTATIVE
            and not user_can_view_planning_event(user, event)
        ):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Cette proposition est en attente de validation par le staff."
            )
        attach_weather([event], concerts_only=True)
        participation = get_participation_for(event, user)
        chat_link = chat_link_for_event(event, user)

        parts = list(
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__last_name",
                "user__first_name",
            )
        )
        counts = {
            "confirmed": 0,
            "invited": 0,
            "maybe": 0,
            "declined": 0,
            "replacement_needed": 0,
        }
        sections_by_code = {
            s.code: s
            for s in OrchestraSection.objects.filter(is_active=True).only(
                "code", "name", "sort_order"
            )
        }
        by_section: dict[str, list] = defaultdict(list)
        section_order: dict[str, int] = {}
        for p in parts:
            if p.status.code in counts:
                counts[p.status.code] += 1
            section = None
            if p.poste:
                code = MusicianProfile.POSTE_SECTION_CODE.get(p.poste)
                if code:
                    section = sections_by_code.get(code)
            if section is None:
                try:
                    section = p.user.musician_profile.section
                except MusicianProfile.DoesNotExist:
                    section = None
            if section:
                section_name = section.name
                section_order.setdefault(section_name, section.sort_order)
            else:
                section_name = "Sans pupitre"
                section_order.setdefault(section_name, 9999)
            by_section[section_name].append(p)
        by_section = {
            name: by_section[name]
            for name in sorted(
                by_section.keys(),
                key=lambda n: (section_order.get(n, 9999), n),
            )
        }

        stage = roster_by_stage(parts)
        taken_ids = {
            p.user_id
            for p in parts
            if getattr(getattr(p, "status", None), "code", None)
            in ("confirmed", "invited", "maybe")
        }
        attach_roster_substitutes(stage, taken_user_ids=taken_ids)

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

        setlist_items = list(setlist.items.all()) if setlist else []
        roadmap = get_roadmap(event)
        attach_calendar_summaries([event])
        draft_proposal = draft_proposal_for_event(event)
        open_proposal = open_proposal_for_event(event)
        open_poll_answered = (
            user_has_answered_poll(user, open_proposal)
            if open_proposal is not None
            else False
        )
        can_cancel_event = bool(
            is_staff
            or (
                event.statut == Event.Statut.TENTATIVE
                and event.proposed_by_id == user.pk
            )
        )

        context.update(
            {
                "event": event,
                "participation": participation,
                "draft_proposal": draft_proposal,
                "open_proposal": open_proposal,
                "open_poll_answered": open_poll_answered,
                "can_cancel_event": can_cancel_event,
                "counts": counts,
                "by_section": by_section,
                "cal_summary": getattr(event, "cal_summary", None) or {},
                "roster_rows": stage["rows"],
                "roster_extras": stage["extras"],
                "roster_unassigned": stage["unassigned"],
                "eligible_subs": eligible,
                "my_sub_requests": my_sub_requests,
                "gear": gear,
                "equipment_catalog": ensure_default_equipment(),
                "chat_link": chat_link,
                "is_planning_staff": is_staff,
                "setlist": setlist,
                "setlist_items": setlist_items,
                "attachable_setlists": attachable_setlists,
                "roadmap": roadmap,
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
        votes_qs = DateVote.objects.select_related("user").order_by(
            "user__last_name", "user__first_name", "user__username"
        )
        proposal = get_object_or_404(
            DateProposal.objects.select_related(
                "linked_event",
                "linked_event__venue",
                "linked_event__type",
                "linked_event__chat_room",
                "source_room",
                "created_by",
            ).prefetch_related(
                Prefetch(
                    "options",
                    queryset=DateOption.objects.prefetch_related(
                        Prefetch("votes", queryset=votes_qs)
                    ).order_by("sort_order", "starts_at", "pk"),
                )
            ),
            pk=kwargs["pk"],
        )
        user = self.request.user
        is_staff = user.is_staff or user.is_superuser
        is_author = proposal.created_by_id == user.pk
        # Brouillon : visible staff ou auteur (pas encore autorisé aux autres).
        if proposal.is_draft and not (is_staff or is_author):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Sondage pas encore lancé par le staff.")
        if not (is_staff or is_author or user_can_access_poll(user, proposal)):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Vous n’êtes pas concerné par ce sondage.")
        # Synthèse avec noms : même source que la modale salon.
        summary = poll_room_summary(proposal, user)
        option_models = {opt.pk: opt for opt in proposal.options.all()}
        options_data = []
        for payload in summary["options"]:
            opt = option_models.get(payload["id"])
            if opt is None:
                continue
            my_vote = next(
                (v for v in opt.votes.all() if v.user_id == user.pk),
                None,
            )
            counts = payload["counts"]
            options_data.append(
                {
                    "option": opt,
                    "counts": counts,
                    "counts_json": json.dumps(counts),
                    "counts_label": format_poll_vote_counts(counts),
                    "my_vote": my_vote.choice if my_vote else None,
                    "yes": payload["yes"],
                    "maybe": payload["maybe"],
                    "no": payload["no"],
                    "total": payload["total"],
                    "voters_json": json.dumps(
                        {
                            "yes": payload["yes"],
                            "maybe": payload["maybe"],
                            "no": payload["no"],
                        }
                    ),
                }
            )
        event = proposal.linked_event
        context.update(
            {
                "proposal": proposal,
                "event": event,
                "options_data": options_data,
                # Même ordre que la synthèse (positif → négatif) pour le select staff.
                "options_ranked": [item["option"] for item in options_data],
                "poll_summary_lead": poll_participation_lead(
                    answered=summary["answered"],
                    audience_count=summary["audience_count"],
                    audience=proposal.audience,
                ),
                "poll_pending": summary["pending"],
                "poll_pending_more": summary["pending_more"],
                "poll_partial": summary["partial"],
                "poll_partial_more": summary["partial_more"],
                "poll_viewer": {
                    "id": user.pk,
                    "name": (
                        (user.get_full_name() or "").strip()
                        or user.username
                        or "Vous"
                    ),
                },
                "poll_viewer_json": json.dumps(
                    {
                        "id": user.pk,
                        "name": (
                            (user.get_full_name() or "").strip()
                            or user.username
                            or "Vous"
                        ),
                    }
                ),
                "is_planning_staff": is_staff,
                "can_edit_deadline": user_can_edit_poll_deadline(user, proposal)
                and proposal.status
                not in (
                    DateProposal.Status.LOCKED,
                    DateProposal.Status.CANCELLED,
                ),
                "can_edit_options": user_can_edit_poll_options(user, proposal)
                and proposal.status
                not in (
                    DateProposal.Status.LOCKED,
                    DateProposal.Status.CANCELLED,
                ),
                "can_edit_meta": user_can_edit_poll_deadline(user, proposal)
                and proposal.status
                not in (
                    DateProposal.Status.LOCKED,
                    DateProposal.Status.CANCELLED,
                ),
                "can_close_poll": user_can_edit_poll_deadline(user, proposal)
                and proposal.is_open,
                "can_manage_poll": user_can_edit_poll_deadline(user, proposal)
                and proposal.is_open,
                "can_delete_poll": user_can_edit_poll_deadline(user, proposal)
                and proposal.status
                not in (
                    DateProposal.Status.LOCKED,
                    DateProposal.Status.CANCELLED,
                ),
                "sibling_polls": sibling_polls_for_user(user, proposal),
                "hide_pending_polls_banner": True,
            }
        )
        # Formulaire de confirmation (création d’événement) pour sondage autonome de dates.
        if (
            is_staff
            and proposal.is_open
            and event is None
            and proposal.is_dates_poll
        ):
            context.update(
                {
                    "venues": Venue.objects.all().order_by("ville", "nom"),
                    "event_types": EventType.objects.all().order_by("nom"),
                    "organismes": _organismes_qs(),
                    "parent_events": _parent_events_qs(),
                    "needs_event_create": True,
                }
            )

        # Salon embarqué : priorité au salon source (plusieurs sondages possibles).
        embed_room = poll_embed_room(proposal)

        if embed_room is not None:
            from chat.services import (
                active_membership,
                build_room_embed_context,
            )

            membership = active_membership(embed_room, user)
            if membership is not None or is_staff:
                embed = build_room_embed_context(self.request, embed_room)
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
            EventParticipation.objects.select_related("status", "event", "event__type"),
            pk=pk,
            user=request.user,
        )
        event = participation.event
        if event.statut == Event.Statut.ANNULE:
            return _json_error("Cet événement est annulé.")
        if not event.is_rehearsal and event.statut == Event.Statut.TENTATIVE:
            return _json_error(
                "Cette date n’est pas encore confirmée : votez d’abord sur le sondage de disponibilité."
            )
        return _respond_participation(request, participation)


class RespondEventView(MusicianRequiredMixin, View):
    """Se positionner sur une date sans invitation préalable."""

    def post(self, request, pk):
        event = get_object_or_404(
            Event.objects.select_related("type"),
            pk=pk,
        )
        if event.statut == Event.Statut.ANNULE:
            return _json_error("Cet événement est annulé.")
        if event.is_rehearsal:
            return _json_error(
                "Pour une répétition, utilisez le signalement d’absence."
            )
        if event.statut == Event.Statut.TENTATIVE:
            return _json_error(
                "Cette date n’est pas encore confirmée : votez d’abord sur le sondage de disponibilité."
            )
        try:
            participation, _ = ensure_open_participation(event, request.user)
        except ValueError as exc:
            return _json_error(str(exc))
        participation = (
            EventParticipation.objects.select_related("status", "event").get(
                pk=participation.pk
            )
        )
        return _respond_participation(request, participation)


def _respond_participation(request, participation: EventParticipation):
    data = _parse_json_body(request)
    response = data.get("response", "")
    maybe_remind_weekly = data.get("maybe_remind_weekly")
    if isinstance(maybe_remind_weekly, str):
        maybe_remind_weekly = maybe_remind_weekly.strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    try:
        set_participation_response(
            participation,
            response,
            comment=data.get("comment", "") or "",
            maybe_remind_at=data.get("maybe_remind_at"),
            maybe_remind_weekly=maybe_remind_weekly,
        )
    except ValueError as exc:
        return _json_error(str(exc))
    participation.refresh_from_db()
    payload = {
        "ok": True,
        "participation_id": participation.pk,
        "status": {
            "code": participation.status.code,
            "label": participation.status.label,
            "color_token": participation.status.color_token,
        },
    }
    if participation.status.code == "maybe":
        payload["maybe_remind"] = {
            "at": (
                participation.maybe_remind_at.isoformat()
                if participation.maybe_remind_at
                else None
            ),
            "weekly": participation.maybe_remind_weekly,
        }
    return JsonResponse(payload)


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
            .exclude(statut=Event.Statut.ANNULE)
            .select_related("venue", "type", "proposed_by")
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
        open_polls = (
            DateProposal.objects.filter(status=DateProposal.Status.OPEN)
            .exclude(source_room__isnull=False, linked_event__isnull=True)
            .select_related("linked_event", "linked_event__venue", "created_by")
            .annotate(n_options=Count("options"))
        )
        draft_polls = (
            DateProposal.objects.filter(status=DateProposal.Status.DRAFT)
            .select_related("linked_event", "linked_event__venue", "created_by")
            .annotate(n_options=Count("options"))
        )
        sections = OrchestraSection.objects.filter(is_active=True)
        equipment = ensure_default_equipment()
        context.update(
            {
                "events": events,
                "open_polls": open_polls,
                "draft_polls": draft_polls,
                "sections": sections,
                "equipment_items": equipment,
                "equipment_categories": EQUIPMENT_CATEGORIES,
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
            Event.objects.select_related("venue", "type", "parent", "chat_room"),
            pk=kwargs["pk"],
        )
        parts = list(
            EventParticipation.objects.filter(event=event)
            .select_related("user", "status", "user__musician_profile__section")
            .order_by(
                "user__last_name",
                "user__first_name",
            )
        )
        stage = roster_by_stage(parts)
        taken_ids = {
            p.user_id
            for p in parts
            if getattr(getattr(p, "status", None), "code", None)
            in ("confirmed", "invited", "maybe")
        }
        attach_roster_substitutes(stage, taken_user_ids=taken_ids)

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
                "roster_rows": stage["rows"],
                "roster_extras": stage["extras"],
                "roster_unassigned": stage["unassigned"],
                "gear": gear,
                "equipment_catalog": ensure_default_equipment(),
                "equipment_categories": EQUIPMENT_CATEGORIES,
                "musicians": musicians,
                "invite_musicians": invite_musicians_for_form(musicians),
                "parent_events": _parent_events_qs(exclude_pk=event.pk),
                "organismes": _organismes_qs(),
                "draft_proposal": draft_proposal_for_event(event),
                "open_proposal": open_proposal_for_event(event),
                "chat_link": chat_link_for_event(event, self.request.user),
                "is_planning_staff": True,
            }
        )
        return context


class UpdateEventPublicationView(PlanningStaffRequiredMixin, View):
    """Organisme + événement parent (dépublication / affiche via le CMS)."""

    def post(self, request, pk):
        event = get_object_or_404(
            Event.objects.select_related("venue", "type"), pk=pk
        )
        event.organisme = _remember_organisme(
            request.POST.get("organisme") or "",
            request.POST.get("organisme_url") or "",
        )
        try:
            event.parent = _resolve_or_create_parent_event(
                request.POST,
                venue=event.venue,
                event_type=event.type,
                date_debut=event.date_debut,
                exclude_pk=event.pk,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:event_roster", pk=event.pk)
        event.save(update_fields=["organisme", "parent"])
        messages.success(
            request,
            f"Organisation de « {event.titre} » enregistrée. "
            "Pour dépublier ou ajuster l’affiche, utilisez le CMS concerts.",
        )
        return redirect("planning:event_roster", pk=event.pk)


class CreatePollView(PlanningStaffRequiredMixin, View):
    def post(self, request):
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Titre requis.")
            return redirect("planning:admin")
        description = (request.POST.get("description") or "").strip()
        deadline_raw = (request.POST.get("deadline") or "").strip()
        deadline = parse_date(deadline_raw) if deadline_raw else None
        if deadline is None:
            messages.error(request, "Indiquez une date limite de réponse.")
            return redirect("planning:admin")
        audience = parse_poll_audience(
            request.POST.get("audience"),
            default=DateProposal.Audience.ALL,
        )
        if audience == DateProposal.Audience.ROOM:
            messages.error(
                request,
                "Un sondage admin autonome doit être ouvert à tout l’orchestre "
                "(pas de salon lié).",
            )
            return redirect("planning:admin")

        from core.ratelimit import claim_once

        option_sig = "|".join(
            sorted(
                (request.POST.get(f"option_starts_{i}") or "").strip()
                for i in range(20)
                if (request.POST.get(f"option_starts_{i}") or "").strip()
            )
        )
        dedupe_key = (
            f"{request.user.pk}:{title.casefold()}:{deadline.isoformat()}:{option_sig}"
        )
        if not claim_once("create_poll", dedupe_key, 45):
            existing = (
                DateProposal.objects.filter(
                    title=title,
                    created_by=request.user,
                    deadline=deadline,
                )
                .exclude(status=DateProposal.Status.CANCELLED)
                .order_by("-id")
                .first()
            )
            messages.warning(
                request,
                "Ce sondage vient d’être créé (double envoi évité).",
            )
            if existing:
                return redirect("planning:poll_detail", pk=existing.pk)
            return redirect("planning:admin")

        # Brouillon : le staff doit lancer explicitement le sondage.
        proposal = DateProposal.objects.create(
            title=title,
            description=description,
            created_by=request.user,
            status=DateProposal.Status.DRAFT,
            deadline=deadline,
            audience=DateProposal.Audience.ALL,
        )
        options_created = 0
        for i in range(20):
            starts = request.POST.get(f"option_starts_{i}")
            if not starts:
                continue
            dt = _parse_local_dt(starts)
            if dt is None:
                continue
            ends_raw = request.POST.get(f"option_ends_{i}") or ""
            ends = _parse_local_dt(ends_raw) if ends_raw else None
            DateOption.objects.create(
                proposal=proposal,
                starts_at=dt,
                ends_at=ends,
                label=(request.POST.get(f"option_label_{i}") or "").strip(),
                sort_order=options_created,
            )
            options_created += 1
        if options_created == 0:
            proposal.delete()
            messages.error(request, "Ajoutez au moins une option de date.")
            return redirect("planning:admin")
        messages.success(
            request,
            "Sondage créé en brouillon — au lancement, "
            f"il notifiera {poll_audience_label(DateProposal.Audience.ALL)}.",
        )
        return redirect("planning:poll_detail", pk=proposal.pk)


class UpdatePollDeadlineView(MusicianRequiredMixin, View):
    """Auteur (ou staff) : modifier la date limite de réponse."""

    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        if not user_can_edit_poll_deadline(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Seul l’auteur ou le staff peut modifier la deadline.")
        if proposal.status in (
            DateProposal.Status.LOCKED,
            DateProposal.Status.CANCELLED,
        ):
            messages.error(request, "Ce sondage est clos — deadline non modifiable.")
            return redirect("planning:poll_detail", pk=pk)
        deadline_raw = (request.POST.get("deadline") or "").strip()
        deadline = parse_date(deadline_raw) if deadline_raw else None
        proposal.deadline = deadline
        # Nouvelle échéance → un nouveau rappel J−7 pourra partir.
        proposal.deadline_reminder_sent_at = None
        proposal.save(
            update_fields=["deadline", "deadline_reminder_sent_at", "updated_at"]
        )
        if deadline:
            messages.success(
                request,
                f"Date limite mise à jour : {deadline.strftime('%d/%m/%Y')}.",
            )
        else:
            messages.success(request, "Date limite retirée.")
        return redirect("planning:poll_detail", pk=pk)


class UpdatePollMetaView(MusicianRequiredMixin, View):
    """Auteur (ou staff) : titre, description, audience."""

    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        if not user_can_edit_poll_deadline(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Seul l’auteur ou le staff peut modifier ce sondage."
            )
        try:
            update_poll_meta(
                proposal,
                title=request.POST.get("title"),
                description=request.POST.get("description"),
                audience=(request.POST.get("audience") or "").strip() or None,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)
        messages.success(request, "Sondage mis à jour.")
        return redirect("planning:poll_detail", pk=pk)


class UpdatePollOptionsView(MusicianRequiredMixin, View):
    """Auteur (ou staff) : modifier / ajouter / retirer des options."""

    def post(self, request, pk):
        proposal = get_object_or_404(
            DateProposal.objects.prefetch_related("options"), pk=pk
        )
        if not user_can_edit_poll_options(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Seul l’auteur ou le staff peut modifier les options du sondage."
            )

        existing_ids = {o.pk for o in proposal.options.all()}
        updates = []
        delete_ids = []
        text_mode = proposal.is_text_poll

        for opt_id in existing_ids:
            if request.POST.get(f"option_delete_{opt_id}"):
                delete_ids.append(opt_id)
                continue
            label = (request.POST.get(f"option_label_{opt_id}") or "").strip()
            if text_mode:
                if not label:
                    messages.error(
                        request,
                        "Chaque option conservée doit avoir un libellé.",
                    )
                    return redirect("planning:poll_detail", pk=pk)
                updates.append({"id": opt_id, "label": label})
                continue
            starts_raw = (request.POST.get(f"option_starts_{opt_id}") or "").strip()
            starts = _parse_local_dt(starts_raw) if starts_raw else None
            if starts is None:
                messages.error(
                    request,
                    "Chaque option conservée doit avoir une date et une heure de début.",
                )
                return redirect("planning:poll_detail", pk=pk)
            ends_raw = (request.POST.get(f"option_ends_{opt_id}") or "").strip()
            ends = _parse_local_dt(ends_raw) if ends_raw else None
            updates.append(
                {
                    "id": opt_id,
                    "starts_at": starts,
                    "ends_at": ends,
                    "label": label,
                }
            )

        new_options = []
        for i in range(20):
            if text_mode:
                label = (request.POST.get(f"new_option_label_{i}") or "").strip()
                if not label:
                    continue
                new_options.append({"label": label})
                continue
            starts_raw = (request.POST.get(f"new_option_starts_{i}") or "").strip()
            if not starts_raw:
                continue
            starts = _parse_local_dt(starts_raw)
            if starts is None:
                continue
            ends_raw = (request.POST.get(f"new_option_ends_{i}") or "").strip()
            ends = _parse_local_dt(ends_raw) if ends_raw else None
            new_options.append(
                {
                    "starts_at": starts,
                    "ends_at": ends,
                    "label": (
                        request.POST.get(f"new_option_label_{i}") or ""
                    ).strip(),
                }
            )

        try:
            update_poll_options(
                proposal,
                updates=updates,
                new_options=new_options,
                delete_ids=delete_ids,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)

        messages.success(request, "Options du sondage mises à jour.")
        return redirect("planning:poll_detail", pk=pk)

class LaunchPollView(PlanningStaffRequiredMixin, View):
    """Autorise / lance le sondage de disponibilité (+ notification)."""

    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        raw_audience = (request.POST.get("audience") or "").strip()
        audience = (
            parse_poll_audience(raw_audience, default=proposal.audience)
            if raw_audience
            else None
        )
        # Sondage sans salon source : défaut orchestre si pas encore précisé.
        if (
            audience is None
            and proposal.audience == DateProposal.Audience.ROOM
            and not proposal.source_room_id
        ):
            audience = DateProposal.Audience.ALL
        try:
            launch_availability_poll(
                proposal,
                launched_by=request.user,
                audience=audience,
                require_recipients=True,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            next_url = (request.POST.get("next") or "").strip()
            if next_url.startswith("/"):
                return redirect(next_url)
            if proposal.linked_event_id:
                return redirect("planning:event_roster", pk=proposal.linked_event_id)
            return redirect("planning:poll_detail", pk=pk)
        proposal.refresh_from_db()
        sent = poll_recipient_count(proposal)
        messages.success(
            request,
            poll_launch_success_message(proposal, sent=sent),
        )
        next_url = (request.POST.get("next") or "").strip()
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect("planning:poll_detail", pk=pk)


class ResendPollNotificationsView(PlanningStaffRequiredMixin, View):
    """Renvoie les notifications push/e-mail d’un sondage déjà ouvert."""

    def post(self, request, pk):
        from planning.services import notify_availability_poll

        proposal = get_object_or_404(DateProposal, pk=pk)
        if not proposal.is_open:
            messages.error(request, "Le sondage n’est pas ouvert.")
            return redirect("planning:poll_detail", pk=pk)
        sent = notify_availability_poll(proposal)
        label = poll_audience_label(proposal.audience)
        messages.success(
            request,
            f"Notifications renvoyées ({sent} destinataire"
            f"{'s' if sent != 1 else ''} · {label}).",
        )
        return redirect("planning:poll_detail", pk=pk)


class RemindPollNonRespondersView(MusicianRequiredMixin, View):
    """Auteur ou staff : relance uniquement les personnes qui n’ont pas répondu."""

    def post(self, request, pk):
        proposal = get_object_or_404(
            DateProposal.objects.prefetch_related("options"), pk=pk
        )
        if not user_can_edit_poll_deadline(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Seul l’auteur ou le staff peut relancer les non-répondants."
            )
        try:
            sent = notify_poll_non_responders(proposal)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)
        if sent == 0:
            messages.info(
                request,
                "Tout le monde a déjà répondu — aucune relance envoyée.",
            )
        else:
            messages.success(
                request,
                f"Relance envoyée à {sent} personne"
                f"{'s' if sent != 1 else ''} "
                f"qui n’{'ont' if sent != 1 else 'a'} pas encore répondu.",
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
        if not proposal.is_open:
            messages.error(request, "Ce sondage n’est plus ouvert.")
            return redirect("planning:poll_detail", pk=pk)
        option_id = request.POST.get("option_id")
        if not option_id:
            messages.error(request, "Choisissez une date à confirmer.")
            return redirect("planning:poll_detail", pk=pk)
        option = get_object_or_404(DateOption, pk=option_id, proposal=proposal)
        if option.starts_at is None:
            messages.error(request, "Cette option n’a pas de date — clôturez le sondage sans créer d’événement.")
            return redirect("planning:poll_detail", pk=pk)

        def _done(default_name: str, **kwargs):
            next_url = (request.POST.get("next") or "").strip()
            if is_safe_local_path(next_url, request):
                return redirect(next_url)
            return redirect(default_name, **kwargs)

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
                f"({option.starts_at.strftime('%d/%m/%Y %H:%M')}). "
                f"Les réponses Oui / Non / Peut-être du sondage ont été "
                f"reportées sur les participations (modifiables ensuite).",
            )
            return _done("planning:poll_detail", pk=pk)

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

        is_rehearsal = bool(getattr(event_type, "is_rehearsal", False)) or (
            "répétition" in (event_type.nom or "").lower()
            or "repetition" in (event_type.nom or "").lower()
        )
        public = not is_rehearsal
        organisme = _remember_organisme(
            request.POST.get("organisme") or "",
            request.POST.get("organisme_url") or "",
        )
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
            statut=Event.Statut.CONFIRME,
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
            f"Événement « {event.titre} » confirmé "
            f"({option.starts_at.strftime('%d/%m/%Y %H:%M')}). "
            f"Invitez les musiciens depuis le roster ou le salon.",
        )
        return _done("planning:event_roster", pk=event.pk)


class ClosePollView(MusicianRequiredMixin, View):
    """Auteur ou staff : clôturer un sondage (sans créer d’événement)."""

    def post(self, request, pk):
        proposal = get_object_or_404(DateProposal, pk=pk)
        if not user_can_edit_poll_deadline(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Seul l’auteur ou le staff peut clôturer ce sondage.")
        if not proposal.is_open:
            messages.error(request, "Ce sondage n’est plus ouvert.")
            return redirect("planning:poll_detail", pk=pk)
        option = None
        option_id = (request.POST.get("option_id") or "").strip()
        if option_id:
            option = get_object_or_404(DateOption, pk=option_id, proposal=proposal)
        try:
            close_poll(proposal, locked_option=option)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)
        messages.success(request, "Sondage clôturé.")
        return redirect("planning:poll_detail", pk=pk)


class CancelPollView(MusicianRequiredMixin, View):
    """Auteur ou staff : supprimer / annuler un sondage ouvert ou brouillon."""

    def post(self, request, pk):
        proposal = get_object_or_404(
            DateProposal.objects.select_related("linked_event"), pk=pk
        )
        if not user_can_edit_poll_deadline(request.user, proposal):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Seul l’auteur ou le staff peut supprimer ce sondage."
            )
        room_id = proposal.source_room_id
        linked = proposal.linked_event
        was_tentative_event = bool(
            linked is not None and linked.statut == Event.Statut.TENTATIVE
        )
        try:
            cancel_poll(proposal)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("planning:poll_detail", pk=pk)
        if was_tentative_event:
            messages.success(
                request,
                f"Proposition « {linked.titre} » et sondage annulés — retirés du calendrier.",
            )
        else:
            messages.success(request, "Sondage supprimé.")
        next_url = (request.POST.get("next") or "").strip()
        if is_safe_local_path(next_url, request):
            return redirect(next_url)
        if room_id:
            return redirect("chat:room", room_id=room_id)
        if linked is not None and not was_tentative_event:
            return redirect("planning:event_detail", pk=linked.pk)
        if request.user.is_staff or request.user.is_superuser:
            return redirect("planning:admin")
        return redirect("planning:dashboard")


class CancelEventView(MusicianRequiredMixin, View):
    """Staff (tout événement) ou auteur (proposition encore tentative) : annuler l’événement."""

    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        is_staff = bool(request.user.is_staff or request.user.is_superuser)
        is_tentative_author = (
            event.statut == Event.Statut.TENTATIVE
            and event.proposed_by_id == request.user.pk
        )
        if not (is_staff or is_tentative_author):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Seul le staff (ou l’auteur d’une proposition non confirmée) peut annuler cet événement."
            )
        was_tentative = event.statut == Event.Statut.TENTATIVE
        cancel_event(event)
        if was_tentative:
            messages.success(
                request,
                f"Proposition « {event.titre} » annulée et retirée du calendrier.",
            )
        else:
            messages.success(
                request,
                f"Événement « {event.titre} » annulé et retiré du calendrier.",
            )
        next_url = (request.POST.get("next") or "").strip()
        if is_safe_local_path(next_url, request):
            return redirect(next_url)
        if is_staff:
            return redirect("planning:admin")
        return redirect("planning:dashboard")


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
            if is_safe_local_path(next_url, request):
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
        if is_safe_local_path(next_url, request):
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
        item_id = (request.POST.get("item_id") or "").strip()
        item_name = (request.POST.get("item_name") or "").strip()
        item_category = (request.POST.get("item_category") or "").strip()

        if item_id == "__new__" or (not item_id and item_name):
            if not item_name:
                messages.error(request, "Indiquez le nom du nouveau matériel.")
                return redirect("planning:event_roster", pk=pk)
            try:
                item = get_or_create_equipment_item(
                    item_name, category=item_category
                )
            except ValueError as exc:
                messages.error(request, str(exc) or "Matériel invalide.")
                return redirect("planning:event_roster", pk=pk)
        else:
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


class SuggestEventEquipmentView(MusicianRequiredMixin, View):
    """Demande / suggestion de matériel par un musicien (pas d’assignation)."""

    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        next_url = (request.POST.get("next") or "").strip()
        if not next_url.startswith("/"):
            if request.user.is_staff or request.user.is_superuser:
                next_url = reverse("planning:event_roster", kwargs={"pk": pk})
            else:
                next_url = reverse("planning:event_detail", kwargs={"pk": pk})
        try:
            assignment = suggest_event_equipment(
                event,
                request.user,
                item_id=request.POST.get("item_id") or "",
                item_name=request.POST.get("item_name") or "",
                note=request.POST.get("note") or "",
            )
        except ValueError as exc:
            messages.error(request, str(exc) or "Proposition invalide.")
            return redirect(next_url)
        messages.success(
            request,
            f"Proposition enregistrée : {assignment.item.name}. "
            "Le staff pourra l’assigner.",
        )
        return redirect(next_url)


class CreateEquipmentItemView(PlanningStaffRequiredMixin, View):
    def post(self, request):
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Nom requis.")
            return redirect("planning:admin")
        try:
            get_or_create_equipment_item(
                name,
                category=(request.POST.get("category") or "").strip(),
            )
        except ValueError as exc:
            messages.error(request, str(exc) or "Matériel invalide.")
            return redirect("planning:admin")
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


class EventRoadmapView(MusicianRequiredMixin, TemplateView):
    """Lecture de la feuille de route (participants + staff)."""

    template_name = "planning/event_roadmap.html"

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(
            Event.objects.select_related("type", "venue"),
            pk=kwargs["pk"],
        )
        if event.is_rehearsal:
            return redirect("repetitions:detail", pk=event.pk)
        participation = get_participation_for(event, request.user)
        if not user_can_view_roadmap(request.user, event, participation):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Feuille de route réservée aux participants.")
        self.event = event
        self.participation = participation
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from core.page_cms import markdown_to_html

        context = super().get_context_data(**kwargs)
        event = self.event
        user = self.request.user
        is_staff = user.is_staff or user.is_superuser
        roadmap = get_roadmap(event)
        md = {}
        if roadmap:
            md = {
                "venue_extra": markdown_to_html(roadmap.venue_extra),
                "parking": markdown_to_html(roadmap.parking_info),
                "material": markdown_to_html(roadmap.material_notes),
                "closing": markdown_to_html(roadmap.closing_note),
                "dress": markdown_to_html(roadmap.dress_code),
            }
        context.update(
            {
                "event": event,
                "roadmap": roadmap,
                "roadmap_md": md,
                "participation": self.participation,
                "is_planning_staff": is_staff,
            }
        )
        return context


class EventRoadmapEditView(PlanningStaffRequiredMixin, View):
    """Édition staff : préremplie + suggestions des feuilles précédentes."""

    template_name = "planning/event_roadmap_edit.html"

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(
            Event.objects.select_related("type", "venue"),
            pk=kwargs["pk"],
        )
        if event.is_rehearsal:
            return redirect("repetitions:detail", pk=event.pk)
        self.event = event
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        roadmap = get_or_create_roadmap(self.event, user=request.user)
        sync_known_fields(roadmap)
        from planning.forms import EventRoadmapForm

        form = EventRoadmapForm(instance=roadmap)
        return self._render(request, form, roadmap)

    def post(self, request, pk):
        roadmap = get_or_create_roadmap(self.event, user=request.user)
        from planning.forms import EventRoadmapForm

        form = EventRoadmapForm(request.POST, instance=roadmap)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.updated_by = request.user
            saved.save()
            messages.success(request, "Feuille de route enregistrée.")
            if request.POST.get("notify"):
                from planning.services.notify_dates import is_past_event

                if is_past_event(self.event):
                    messages.warning(
                        request,
                        "Date dépassée — aucune notification envoyée.",
                    )
                else:
                    n = notify_roadmap(self.event, actor=request.user)
                    messages.success(
                        request,
                        f"Notification envoyée à {n} participant"
                        f"{'s' if n != 1 else ''}.",
                    )
            return redirect("planning:event_roadmap", pk=self.event.pk)
        return self._render(request, form, roadmap)

    def _render(self, request, form, roadmap):
        from django.shortcuts import render

        suggestions = suggest_defaults(self.event)
        return render(
            request,
            self.template_name,
            {
                "event": self.event,
                "roadmap": roadmap,
                "form": form,
                "suggestions": suggestions,
                "is_planning_staff": True,
            },
        )


class EventRoadmapNotifyView(PlanningStaffRequiredMixin, View):
    """Envoie la notification feuille de route aux participants."""

    def post(self, request, pk):
        event = get_object_or_404(
            Event.objects.select_related("type"),
            pk=pk,
        )
        if event.is_rehearsal:
            return redirect("repetitions:detail", pk=event.pk)
        roadmap = get_roadmap(event)
        if roadmap is None:
            messages.error(request, "Créez d’abord la feuille de route.")
            return redirect("planning:event_roadmap_edit", pk=event.pk)
        from planning.services.notify_dates import is_past_event

        if is_past_event(event):
            messages.warning(
                request, "Date dépassée — aucune notification envoyée."
            )
        else:
            n = notify_roadmap(event, actor=request.user)
            messages.success(
                request,
                f"Notification envoyée à {n} participant{'s' if n != 1 else ''}.",
            )
        return redirect("planning:event_roadmap", pk=event.pk)
