from __future__ import annotations

import tempfile
from pathlib import Path

from django.core.exceptions import ObjectDoesNotExist
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from chat.services import ensure_piece_room, notify_piece_chorus_update
from planning.models import MusicianProfile
from planning.views import PlanningStaffRequiredMixin
from repertoire.forms import (
    ImagesToPartForm,
    PartUploadForm,
    PdfSplitForm,
    PieceForm,
    SetlistDuplicateForm,
    SetlistForm,
)
from repertoire.models import Part, PartPoste, Piece, Setlist
from repertoire.pdf_utils import (
    extract_pdf_pages_bytes,
    images_to_pdf_bytes,
)
from users.roles import MusicianRequiredMixin


def _user_default_poste(user) -> str:
    try:
        profile = user.musician_profile
    except MusicianProfile.DoesNotExist:
        return ""
    return profile.poste_titulaire or ""


def _save_part_pdf(piece: Piece, poste: str, data: bytes, filename: str, source_name: str = "") -> Part:
    part, _ = Part.objects.update_or_create(
        piece=piece,
        poste=poste,
        defaults={
            "source_name": source_name or filename,
            "sort_order": 0,
        },
    )
    part.file.save(filename, ContentFile(data), save=True)
    return part


# ---------------------------------------------------------------------------
# Musician-facing
# ---------------------------------------------------------------------------


class PieceListView(MusicianRequiredMixin, ListView):
    template_name = "repertoire/piece_list.html"
    context_object_name = "pieces"

    def get_queryset(self):
        qs = Piece.objects.filter(is_published=True).prefetch_related("parts")
        poste = self.request.GET.get("poste", "").strip()
        if poste == "":
            poste = _user_default_poste(self.request.user)
        self._poste = poste
        if poste and poste != "all":
            qs = qs.filter(parts__poste=poste).distinct()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        poste = getattr(self, "_poste", "") or "all"
        ctx["selected_poste"] = poste if poste else "all"
        ctx["poste_choices"] = PartPoste.choices
        ctx["is_planning_staff"] = self.request.user.is_staff or self.request.user.is_superuser
        # Annotate matching part for current filter
        parts_by_piece = {}
        if poste and poste != "all":
            for piece in ctx["pieces"]:
                part = next((p for p in piece.parts.all() if p.poste == poste), None)
                parts_by_piece[piece.pk] = part
        ctx["parts_by_piece"] = parts_by_piece
        return ctx


class PieceDetailView(MusicianRequiredMixin, DetailView):
    template_name = "repertoire/piece_detail.html"
    context_object_name = "piece"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        qs = Piece.objects.prefetch_related("parts")
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            qs = qs.filter(is_published=True)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        poste = self.request.GET.get("poste", "").strip()
        if poste == "":
            poste = _user_default_poste(self.request.user)
        parts = list(self.object.parts.all())
        if poste and poste != "all":
            filtered = [p for p in parts if p.poste == poste]
        else:
            filtered = parts
        ctx["selected_poste"] = poste if poste else "all"
        ctx["poste_choices"] = PartPoste.choices
        ctx["parts"] = filtered
        ctx["all_parts"] = parts
        ctx["is_planning_staff"] = self.request.user.is_staff or self.request.user.is_superuser
        try:
            ctx["chat_room"] = self.object.chat_room
        except ObjectDoesNotExist:
            ctx["chat_room"] = None
        return ctx


class PartDownloadView(MusicianRequiredMixin, View):
    def get(self, request, pk: int):
        part = get_object_or_404(Part.objects.select_related("piece"), pk=pk)
        if not part.piece.is_published and not (
            request.user.is_staff or request.user.is_superuser
        ):
            raise Http404
        if not part.file:
            raise Http404
        return FileResponse(
            part.file.open("rb"),
            as_attachment=False,
            filename=Path(part.file.name).name,
            content_type="application/pdf",
        )


class CreatePieceSalonView(MusicianRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        if not piece.is_published and not (
            request.user.is_staff or request.user.is_superuser
        ):
            raise Http404
        room = ensure_piece_room(piece)
        return redirect("chat:room", room_id=room.pk)


# ---------------------------------------------------------------------------
# Staff — pieces
# ---------------------------------------------------------------------------


class StaffPieceListView(PlanningStaffRequiredMixin, ListView):
    template_name = "repertoire/staff_piece_list.html"
    context_object_name = "pieces"
    queryset = Piece.objects.prefetch_related("parts").order_by("title")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["is_planning_staff"] = True
        return ctx


class StaffPieceCreateView(PlanningStaffRequiredMixin, FormView):
    template_name = "repertoire/staff_piece_form.html"
    form_class = PieceForm

    def form_valid(self, form):
        piece = form.save(commit=False)
        if form.cleaned_data.get("chorus_order"):
            piece.chorus_order_updated_at = timezone.now()
        piece.save()
        messages.success(self.request, f"Morceau « {piece.title} » créé.")
        return redirect("repertoire:staff_piece_edit", slug=piece.slug)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["piece"] = None
        ctx["is_planning_staff"] = True
        return ctx


class StaffPieceEditView(PlanningStaffRequiredMixin, View):
    template_name = "repertoire/staff_piece_form.html"

    def get_piece(self, slug: str) -> Piece:
        return get_object_or_404(Piece.objects.prefetch_related("parts"), slug=slug)

    def get(self, request, slug: str):
        piece = self.get_piece(slug)
        form = PieceForm(instance=piece)
        return self._render(request, piece, form)

    def post(self, request, slug: str):
        piece = self.get_piece(slug)
        old_chorus = piece.chorus_order
        form = PieceForm(request.POST, request.FILES, instance=piece)
        if not form.is_valid():
            return self._render(request, piece, form)
        piece = form.save(commit=False)
        new_chorus = (piece.chorus_order or "").strip()
        if new_chorus != (old_chorus or "").strip():
            piece.chorus_order_updated_at = timezone.now()
            piece.save()
            notify_piece_chorus_update(piece, author=request.user)
        else:
            piece.save()
        messages.success(request, "Morceau enregistré.")
        return redirect("repertoire:staff_piece_edit", slug=piece.slug)

    def _render(self, request, piece, form):
        from django.template.response import TemplateResponse

        return TemplateResponse(
            request,
            self.template_name,
            {
                "form": form,
                "piece": piece,
                "parts": list(piece.parts.all()),
                "upload_form": PartUploadForm(),
                "images_form": ImagesToPartForm(),
                "split_form": PdfSplitForm(),
                "is_planning_staff": True,
            },
        )


class StaffPartUploadView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        form = PartUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Upload invalide.")
            return redirect("repertoire:staff_piece_edit", slug=slug)
        f = form.cleaned_data["file"]
        data = f.read()
        filename = f"{slugify(piece.title)}-{form.cleaned_data['poste']}.pdf"
        _save_part_pdf(
            piece,
            form.cleaned_data["poste"],
            data,
            filename,
            source_name=form.cleaned_data.get("source_name") or f.name,
        )
        messages.success(request, "Partition enregistrée.")
        return redirect("repertoire:staff_piece_edit", slug=slug)


class StaffPartImagesView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        form = ImagesToPartForm(request.POST, request.FILES)
        files = request.FILES.getlist("images")
        if not form.is_valid() or not files:
            messages.error(request, "Sélectionnez au moins une image.")
            return redirect("repertoire:staff_piece_edit", slug=slug)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, f in enumerate(files):
                dest = Path(tmp) / f"{i:03d}_{f.name}"
                dest.write_bytes(f.read())
                paths.append(dest)
            try:
                data = images_to_pdf_bytes(paths)
            except Exception as exc:
                messages.error(request, f"Conversion impossible : {exc}")
                return redirect("repertoire:staff_piece_edit", slug=slug)
        filename = f"{slugify(piece.title)}-{form.cleaned_data['poste']}.pdf"
        _save_part_pdf(piece, form.cleaned_data["poste"], data, filename, source_name="images")
        messages.success(request, f"PDF créé à partir de {len(files)} image(s).")
        return redirect("repertoire:staff_piece_edit", slug=slug)


class StaffPartSplitView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        form = PdfSplitForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Découpe invalide.")
            return redirect("repertoire:staff_piece_edit", slug=slug)
        src = form.cleaned_data["source_pdf"]
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(src.read())
            tmp.flush()
            try:
                data = extract_pdf_pages_bytes(
                    tmp.name,
                    form.cleaned_data["page_start"],
                    form.cleaned_data["page_end"],
                )
            except Exception as exc:
                messages.error(request, f"Découpe impossible : {exc}")
                return redirect("repertoire:staff_piece_edit", slug=slug)
        filename = f"{slugify(piece.title)}-{form.cleaned_data['poste']}.pdf"
        _save_part_pdf(
            piece,
            form.cleaned_data["poste"],
            data,
            filename,
            source_name=src.name,
        )
        messages.success(
            request,
            f"Pages {form.cleaned_data['page_start']}–{form.cleaned_data['page_end']} "
            f"extraites vers {dict(PartPoste.choices).get(form.cleaned_data['poste'])}.",
        )
        return redirect("repertoire:staff_piece_edit", slug=slug)


class StaffPartDeleteView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk: int):
        part = get_object_or_404(Part.objects.select_related("piece"), pk=pk)
        slug = part.piece.slug
        part.file.delete(save=False)
        part.delete()
        messages.success(request, "Partition supprimée.")
        return redirect("repertoire:staff_piece_edit", slug=slug)


# ---------------------------------------------------------------------------
# Staff — setlists
# ---------------------------------------------------------------------------


def _parse_setlist_piece_ids(request) -> list[int]:
    raw = request.POST.getlist("piece_ids")
    ids: list[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _parse_setlist_notes(request, piece_ids: list[int]) -> dict[int, str]:
    notes: dict[int, str] = {}
    for pid in piece_ids:
        notes[pid] = (request.POST.get(f"note_{pid}") or "").strip()
    return notes


def _setlist_builder_context(setlist: Setlist | None) -> dict:
    pieces = list(Piece.objects.order_by("title").values("id", "title"))
    selected: list[dict] = []
    if setlist is not None:
        selected = [
            {
                "id": item.piece_id,
                "title": item.piece.title,
                "note": item.note,
            }
            for item in setlist.items.select_related("piece").order_by("position", "id")
        ]
    return {"builder_pieces": pieces, "builder_selected": selected}


class StaffSetlistListView(PlanningStaffRequiredMixin, ListView):
    template_name = "repertoire/staff_setlist_list.html"
    context_object_name = "setlists"
    queryset = Setlist.objects.select_related("event").order_by("-updated_at")


class StaffSetlistCreateView(PlanningStaffRequiredMixin, View):
    template_name = "repertoire/staff_setlist_form.html"

    def get(self, request):
        return self._render(request, SetlistForm(), None)

    def post(self, request):
        form = SetlistForm(request.POST)
        piece_ids = _parse_setlist_piece_ids(request)
        notes = _parse_setlist_notes(request, piece_ids)
        if not form.is_valid():
            return self._render(request, form, None, piece_ids=piece_ids, notes=notes)
        with transaction.atomic():
            setlist = form.save(commit=False)
            setlist.created_by = request.user
            if setlist.event_id and setlist.is_active:
                Setlist.objects.filter(event_id=setlist.event_id, is_active=True).update(
                    is_active=False
                )
            setlist.save()
            setlist.sync_items(piece_ids, notes)
        messages.success(request, "Setlist créée.")
        return redirect("repertoire:staff_setlist_edit", pk=setlist.pk)

    def _render(self, request, form, setlist, piece_ids=None, notes=None):
        from django.template.response import TemplateResponse

        ctx = {
            "form": form,
            "setlist": setlist,
            "is_planning_staff": True,
            **_setlist_builder_context(setlist),
        }
        if piece_ids is not None:
            titles = {
                p["id"]: p["title"] for p in ctx["builder_pieces"]
            }
            notes = notes or {}
            ctx["builder_selected"] = [
                {
                    "id": pid,
                    "title": titles.get(pid, f"#{pid}"),
                    "note": notes.get(pid, ""),
                }
                for pid in piece_ids
                if pid in titles
            ]
        return TemplateResponse(request, self.template_name, ctx)


class StaffSetlistEditView(PlanningStaffRequiredMixin, View):
    template_name = "repertoire/staff_setlist_form.html"

    def get(self, request, pk: int):
        setlist = get_object_or_404(Setlist, pk=pk)
        return self._render(request, SetlistForm(instance=setlist), setlist)

    def post(self, request, pk: int):
        setlist = get_object_or_404(Setlist, pk=pk)
        form = SetlistForm(request.POST, instance=setlist)
        piece_ids = _parse_setlist_piece_ids(request)
        notes = _parse_setlist_notes(request, piece_ids)
        if not form.is_valid():
            return self._render(
                request, form, setlist, piece_ids=piece_ids, notes=notes
            )
        with transaction.atomic():
            setlist = form.save(commit=False)
            if setlist.event_id and setlist.is_active:
                Setlist.objects.filter(event_id=setlist.event_id, is_active=True).exclude(
                    pk=setlist.pk
                ).update(is_active=False)
            setlist.save()
            setlist.sync_items(piece_ids, notes)
        messages.success(request, "Setlist enregistrée.")
        return redirect("repertoire:staff_setlist_edit", pk=setlist.pk)

    def _render(self, request, form, setlist, piece_ids=None, notes=None):
        from django.template.response import TemplateResponse

        ctx = {
            "form": form,
            "setlist": setlist,
            "duplicate_form": SetlistDuplicateForm(
                initial={"title": f"{setlist.title} (copie)"}
            ),
            "is_planning_staff": True,
            **_setlist_builder_context(setlist),
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
                if pid in titles
            ]
        return TemplateResponse(request, self.template_name, ctx)


class StaffSetlistDuplicateView(PlanningStaffRequiredMixin, View):
    def post(self, request, pk: int):
        setlist = get_object_or_404(Setlist, pk=pk)
        form = SetlistDuplicateForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Duplication invalide.")
            return redirect("repertoire:staff_setlist_edit", pk=pk)
        event = form.cleaned_data.get("event")
        with transaction.atomic():
            if event:
                Setlist.objects.filter(event=event, is_active=True).update(is_active=False)
            new = setlist.duplicate(
                title=form.cleaned_data["title"],
                event=event,
                created_by=request.user,
            )
        messages.success(request, f"Setlist dupliquée : {new.title}.")
        return redirect("repertoire:staff_setlist_edit", pk=new.pk)
