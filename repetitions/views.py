from __future__ import annotations

from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from events.models import Event
from planning.models import EventParticipation, SubstituteRequest
from planning.services import chat_link_for_event, get_participation_for
from planning.views import PlanningStaffRequiredMixin
from repertoire.models import Piece
from repetitions.forms import (
    RehearsalCreateForm,
    RehearsalEditForm,
    venue_initial_from_event,
)
from repetitions.models import RehearsalPlan
from repetitions.services import (
    DEFAULT_REHEARSAL_VENUE_NOM,
    absent_with_eligible_subs,
    attendance_for_event,
    create_rehearsal,
    get_or_create_plan,
    notify_substitute_for_absence,
    resolve_rehearsal_venue,
    set_rehearsal_absence,
    sync_roadmap_items,
)
from users.roles import MusicianRequiredMixin

User = get_user_model()


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_piece_ids(request: HttpRequest) -> list[int]:
    raw = request.POST.getlist("piece_ids")
    if not raw and request.POST.get("piece_ids_csv"):
        raw = (request.POST.get("piece_ids_csv") or "").split(",")
    ids: list[int] = []
    for value in raw:
        value = (value or "").strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _parse_piece_notes(request: HttpRequest, piece_ids: list[int]) -> dict[int, str]:
    return {
        pid: (request.POST.get(f"note_{pid}") or "").strip() for pid in piece_ids
    }


def _builder_context(plan: RehearsalPlan | None) -> dict:
    pieces = list(Piece.objects.order_by("title").values("id", "title"))
    selected: list[dict] = []
    if plan is not None:
        selected = [
            {
                "id": item.piece_id,
                "title": item.piece.title,
                "note": item.note,
            }
            for item in plan.items.select_related("piece").order_by("position", "id")
        ]
    return {"builder_pieces": pieces, "builder_selected": selected}


def _combine_local(day, t: time | None):
    if t is None:
        return None
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, t), tz)


def _upcoming_rehearsals_qs():
    now = timezone.now()
    return (
        Event.objects.filter(date_debut__gte=now)
        .filter(Q(type__nom__icontains="épétition") | Q(type__nom__icontains="repetition"))
        .select_related("venue", "type")
        .order_by("date_debut")
    )


def get_rehearsal_event(pk: int) -> Event:
    event = get_object_or_404(
        Event.objects.select_related("venue", "type", "chat_room", "rehearsal_plan"),
        pk=pk,
    )
    if not event.is_rehearsal:
        from django.http import Http404

        raise Http404("Ce n’est pas une répétition.")
    return event


# ---------------------------------------------------------------------------
# Musician
# ---------------------------------------------------------------------------


class RehearsalDetailView(MusicianRequiredMixin, TemplateView):
    template_name = "repetitions/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_rehearsal_event(kwargs["pk"])
        user = self.request.user
        participation = get_participation_for(event, user)
        try:
            plan = event.rehearsal_plan
        except RehearsalPlan.DoesNotExist:
            plan = None

        is_staff = user.is_staff or user.is_superuser
        attendance = attendance_for_event(event) if is_staff else None
        absent_rows = absent_with_eligible_subs(event) if is_staff else []

        items = []
        if plan is not None:
            items = list(plan.items.select_related("piece").order_by("position", "id"))

        absent = False
        if participation is not None:
            absent = participation.status.code in ("declined", "replacement_needed")

        my_sub_offer = (
            SubstituteRequest.objects.filter(
                candidate=user,
                status=SubstituteRequest.Status.PROPOSED,
                participation__event=event,
            )
            .select_related("participation", "participation__user")
            .first()
        )

        context.update(
            {
                "event": event,
                "plan": plan,
                "items": items,
                "participation": participation,
                "is_absent": absent,
                "my_sub_offer": my_sub_offer,
                "chat_link": chat_link_for_event(event, user),
                "is_planning_staff": is_staff,
                "attendance": attendance,
                "absent_rows": absent_rows,
            }
        )
        return context


class ToggleAbsenceView(MusicianRequiredMixin, View):
    """POST JSON {absent: true|false}."""

    def post(self, request, pk):
        event = get_rehearsal_event(pk)
        participation = get_participation_for(event, request.user)
        if participation is None:
            return _json_error("Vous n’êtes pas inscrit à cette répétition.", 403)

        import json

        try:
            if request.content_type and "application/json" in request.content_type:
                body = json.loads(request.body.decode() or "{}")
            else:
                body = request.POST
        except json.JSONDecodeError:
            body = {}

        raw = body.get("absent", True)
        if isinstance(raw, str):
            absent = raw.lower() in ("1", "true", "yes", "on")
        else:
            absent = bool(raw)

        try:
            part = set_rehearsal_absence(participation, absent=absent)
        except ValueError as exc:
            return _json_error(str(exc))

        return JsonResponse(
            {
                "ok": True,
                "absent": part.status.code in ("declined", "replacement_needed"),
                "status": part.status.code,
                "label": "Absent" if absent else "Présent",
            }
        )


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


class StaffRehearsalListView(PlanningStaffRequiredMixin, TemplateView):
    template_name = "repetitions/staff_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "events": list(_upcoming_rehearsals_qs()[:40]),
                "is_planning_staff": True,
            }
        )
        return context


class StaffRehearsalCreateView(PlanningStaffRequiredMixin, View):
    template_name = "repetitions/staff_form.html"

    def get(self, request):
        preset = timezone.localdate()
        raw = (request.GET.get("date") or "").strip()
        if raw:
            try:
                from datetime import date as date_cls

                preset = date_cls.fromisoformat(raw)
            except ValueError:
                pass
        form = RehearsalCreateForm(
            initial={
                "date": preset,
                "time_start": time(20, 0),
            }
        )
        return self._render(request, form, None)

    def post(self, request):
        form = RehearsalCreateForm(request.POST)
        piece_ids = _parse_piece_ids(request)
        notes = _parse_piece_notes(request, piece_ids)
        if not form.is_valid():
            return self._render(
                request, form, None, piece_ids=piece_ids, notes=notes
            )
        data = form.cleaned_data
        date_debut = _combine_local(data["date"], data["time_start"])
        date_fin = _combine_local(data["date"], data.get("time_end"))
        try:
            venue = resolve_rehearsal_venue(
                mode=data.get("venue_mode") or "default",
                nom=data.get("venue_nom") or "",
                ville=data.get("venue_ville") or "",
                adresse=data.get("venue_adresse") or "",
            )
            event, plan = create_rehearsal(
                titre=data["titre"],
                venue=venue,
                date_debut=date_debut,
                date_fin=date_fin,
                description=data.get("description") or "",
                notes=data.get("notes") or "",
                created_by=request.user,
                piece_ids=piece_ids,
                notes_by_piece=notes,
                notify_musicians=bool(data.get("notify_musicians")),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return self._render(
                request, form, None, piece_ids=piece_ids, notes=notes
            )
        messages.success(request, "Répétition créée — titulaires inscrits présents.")
        return redirect("repetitions:staff_edit", pk=event.pk)

    def _render(self, request, form, plan, piece_ids=None, notes=None):
        ctx = {
            "form": form,
            "plan": plan,
            "event": None,
            "is_planning_staff": True,
            "creating": True,
            "default_rehearsal_venue_nom": DEFAULT_REHEARSAL_VENUE_NOM,
            **_builder_context(plan),
        }
        if piece_ids is not None:
            titles = {p["id"]: p["title"] for p in ctx["builder_pieces"]}
            notes = notes or {}
            ctx["builder_selected"] = [
                {
                    "id": pid,
                    "title": titles.get(pid, f"#{pid}"),
                    "note": notes.get(pid, ""),
                }
                for pid in piece_ids
            ]
        return TemplateResponse(request, self.template_name, ctx)


class StaffRehearsalEditView(PlanningStaffRequiredMixin, View):
    template_name = "repetitions/staff_form.html"

    def get(self, request, pk):
        event = get_rehearsal_event(pk)
        plan = get_or_create_plan(event, user=request.user)
        local_start = timezone.localtime(event.date_debut)
        local_end = timezone.localtime(event.date_fin) if event.date_fin else None
        form = RehearsalEditForm(
            initial={
                "titre": event.titre,
                "date": local_start.date(),
                "time_start": local_start.time().replace(microsecond=0),
                "time_end": (
                    local_end.time().replace(microsecond=0) if local_end else None
                ),
                "description": event.description,
                "notes": plan.notes,
                "statut": event.statut,
                **venue_initial_from_event(event.venue),
            }
        )
        return self._render(request, form, event, plan)

    def post(self, request, pk):
        event = get_rehearsal_event(pk)
        plan = get_or_create_plan(event, user=request.user)
        form = RehearsalEditForm(request.POST)
        piece_ids = _parse_piece_ids(request)
        notes = _parse_piece_notes(request, piece_ids)
        if not form.is_valid():
            return self._render(
                request, form, event, plan, piece_ids=piece_ids, notes=notes
            )
        data = form.cleaned_data
        try:
            venue = resolve_rehearsal_venue(
                mode=data.get("venue_mode") or "default",
                nom=data.get("venue_nom") or "",
                ville=data.get("venue_ville") or "",
                adresse=data.get("venue_adresse") or "",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return self._render(
                request, form, event, plan, piece_ids=piece_ids, notes=notes
            )
        with transaction.atomic():
            event.titre = data["titre"].strip()
            event.venue = venue
            event.description = (data.get("description") or "").strip()
            event.statut = data["statut"]
            event.date_debut = _combine_local(data["date"], data["time_start"])
            event.date_fin = _combine_local(data["date"], data.get("time_end"))
            event.save()
            plan.notes = (data.get("notes") or "").strip()
            plan.updated_by = request.user
            plan.save(update_fields=["notes", "updated_by", "updated_at"])
            sync_roadmap_items(plan, piece_ids, notes)
        messages.success(request, "Répétition mise à jour.")
        return redirect("repetitions:staff_edit", pk=event.pk)

    def _render(self, request, form, event, plan, piece_ids=None, notes=None):
        ctx = {
            "form": form,
            "plan": plan,
            "event": event,
            "is_planning_staff": True,
            "creating": False,
            "default_rehearsal_venue_nom": DEFAULT_REHEARSAL_VENUE_NOM,
            "attendance": attendance_for_event(event),
            "absent_rows": absent_with_eligible_subs(event),
            **_builder_context(plan),
        }
        if piece_ids is not None:
            titles = {p["id"]: p["title"] for p in ctx["builder_pieces"]}
            notes = notes or {}
            ctx["builder_selected"] = [
                {
                    "id": pid,
                    "title": titles.get(pid, f"#{pid}"),
                    "note": notes.get(pid, ""),
                }
                for pid in piece_ids
            ]
        return TemplateResponse(request, self.template_name, ctx)


class StaffNotifySubstituteView(PlanningStaffRequiredMixin, View):
    """POST : notifie un remplaçant pour un titulaire absent."""

    def post(self, request, pk):
        event = get_rehearsal_event(pk)
        import json

        try:
            if request.content_type and "application/json" in request.content_type:
                body = json.loads(request.body.decode() or "{}")
            else:
                body = request.POST
        except json.JSONDecodeError:
            body = {}

        try:
            part_id = int(body.get("participation_id") or 0)
            candidate_id = int(body.get("candidate_id") or 0)
        except (TypeError, ValueError):
            return _json_error("Paramètres invalides.")

        participation = get_object_or_404(
            EventParticipation.objects.select_related("event", "status", "user"),
            pk=part_id,
            event=event,
        )
        if participation.status.code not in ("declined", "replacement_needed"):
            return _json_error("Ce musicien n’est pas marqué absent.")

        candidate = get_object_or_404(User, pk=candidate_id, is_musician=True, is_active=True)
        note = (body.get("note") or "").strip()
        try:
            sent = notify_substitute_for_absence(
                participation, candidate, note=note
            )
        except ValueError as exc:
            return _json_error(str(exc))

        return JsonResponse(
            {
                "ok": True,
                "notified": sent,
                "message": (
                    f"Remplaçant notifié ({candidate.get_full_name() or candidate.username})."
                    if sent
                    else "Demande créée (notification non envoyée)."
                ),
            }
        )
