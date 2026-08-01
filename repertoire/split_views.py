"""Vues staff — éditeur graphique de découpe PDF (miniatures + plages contiguës)."""

from __future__ import annotations

import json

from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views import View

from planning.views import PlanningStaffRequiredMixin
from repertoire import split_store
from repertoire.models import PartPoste, Piece
from repertoire.pdf_utils import (
    extract_pdf_pages_bytes,
    render_pdf_page_jpeg,
    rotate_pdf_page,
)


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_json_body(request: HttpRequest) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def validate_split_ranges(
    ranges: list, page_count: int
) -> tuple[list[dict] | None, str | None]:
    """Un intervalle [start, end] par poste, sans chevauchement."""
    valid_postes = {c.value for c in PartPoste}
    if not isinstance(ranges, list) or not ranges:
        return None, "Ajoutez au moins une plage."
    cleaned: list[dict] = []
    seen_postes: set[str] = set()
    occupied: list[tuple[int, int, str]] = []
    for raw in ranges:
        if not isinstance(raw, dict):
            return None, "Plage invalide."
        poste = (raw.get("poste") or "").strip()
        try:
            start = int(raw.get("start"))
            end = int(raw.get("end"))
        except (TypeError, ValueError):
            return None, "Pages invalides."
        if poste not in valid_postes:
            return None, f"Poste inconnu : {poste}."
        if poste in seen_postes:
            return None, f"Une seule plage par poste ({poste})."
        if start < 1 or end < start or end > page_count:
            return None, f"Plage hors limites pour {poste}."
        for a, b, other in occupied:
            if not (end < a or start > b):
                return None, f"Chevauchement entre {poste} et {other}."
        seen_postes.add(poste)
        occupied.append((start, end, poste))
        cleaned.append({"poste": poste, "start": start, "end": end})
    cleaned.sort(key=lambda r: r["start"])
    return cleaned, None


class StaffPieceDecoupeView(PlanningStaffRequiredMixin, View):
    template_name = "repertoire/staff_piece_split.html"

    def get(self, request, slug: str):
        from django.template.response import TemplateResponse

        piece = get_object_or_404(Piece.objects.prefetch_related("parts"), slug=slug)
        source = split_store.load_from_session(request.session, piece.pk)
        existing = sorted(piece.parts.values_list("poste", flat=True))
        postes = [{"value": v, "label": lab} for v, lab in PartPoste.choices]
        server_files = [
            c.to_json()
            for c in split_store.list_server_candidates(
                title=piece.title, slug=piece.slug
            )
        ]
        return TemplateResponse(
            request,
            self.template_name,
            {
                "piece": piece,
                "is_planning_staff": True,
                "source": source,
                "page_count": source.page_count if source else 0,
                "source_name": source.source_name if source else "",
                "postes_json": postes,
                "existing_postes_json": existing,
                "server_files_json": server_files,
            },
        )


class StaffPieceDecoupeUploadView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        f = request.FILES.get("source_pdf")
        if not f:
            return _json_error("Choisissez un PDF.")
        name = (getattr(f, "name", "") or "").lower()
        ctype = (getattr(f, "content_type", "") or "").lower()
        if not (name.endswith(".pdf") or ctype == "application/pdf"):
            return _json_error("Le fichier doit être un PDF.")
        split_store.clear_session(request.session, piece.pk)
        try:
            source = split_store.create_from_upload(
                f, source_name=getattr(f, "name", "")
            )
        except ValueError as exc:
            return _json_error(str(exc))
        split_store.save_to_session(request.session, piece.pk, source)
        return JsonResponse(
            {
                "ok": True,
                "page_count": source.page_count,
                "source_name": source.source_name,
            }
        )


class StaffPieceDecoupeFromServerView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        body = _parse_json_body(request)
        candidate_id = (body.get("id") or request.POST.get("id") or "").strip()
        if not candidate_id:
            return _json_error("Choisissez un fichier serveur.")
        path = split_store.resolve_candidate(candidate_id)
        if path is None:
            return _json_error("Fichier introuvable ou non autorisé.", status=404)
        # Must still match this piece (avoid loading unrelated PDFs by guessing ids)
        allowed_ids = {
            c.id
            for c in split_store.list_server_candidates(
                title=piece.title, slug=piece.slug
            )
        }
        if candidate_id not in allowed_ids:
            return _json_error("Ce fichier ne correspond pas à ce morceau.", status=403)
        split_store.clear_session(request.session, piece.pk)
        try:
            source = split_store.create_from_server_file(path)
        except ValueError as exc:
            return _json_error(str(exc))
        split_store.save_to_session(request.session, piece.pk, source)
        return JsonResponse(
            {
                "ok": True,
                "page_count": source.page_count,
                "source_name": source.source_name,
            }
        )


class StaffPieceDecoupeThumbView(PlanningStaffRequiredMixin, View):
    def get(self, request, slug: str, page: int):
        piece = get_object_or_404(Piece, slug=slug)
        source = split_store.load_from_session(request.session, piece.pk)
        if source is None:
            raise Http404
        if page < 1 or page > source.page_count:
            raise Http404
        thumb = source.thumb_path(page)
        if not thumb.is_file():
            try:
                data = render_pdf_page_jpeg(
                    source.pdf_path, page, max_width=360, quality=68
                )
            except ValueError as exc:
                raise Http404 from exc
            thumb.parent.mkdir(parents=True, exist_ok=True)
            thumb.write_bytes(data)
        return FileResponse(thumb.open("rb"), content_type="image/jpeg")


class StaffPieceDecoupePreviewView(PlanningStaffRequiredMixin, View):
    def get(self, request, slug: str, page: int):
        piece = get_object_or_404(Piece, slug=slug)
        source = split_store.load_from_session(request.session, piece.pk)
        if source is None:
            raise Http404
        if page < 1 or page > source.page_count:
            raise Http404
        try:
            data = render_pdf_page_jpeg(
                source.pdf_path, page, max_width=900, quality=78
            )
        except ValueError as exc:
            raise Http404 from exc
        return HttpResponse(data, content_type="image/jpeg")


class StaffPieceDecoupeRotateView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str, page: int):
        piece = get_object_or_404(Piece, slug=slug)
        source = split_store.load_from_session(request.session, piece.pk)
        if source is None:
            return _json_error("Aucun PDF source. Rechargez un fichier.", status=404)
        if page < 1 or page > source.page_count:
            return _json_error("Page hors limites.")
        body = _parse_json_body(request)
        direction = (body.get("direction") or request.POST.get("direction") or "").strip()
        if direction == "left":
            degrees = -90
        elif direction == "right":
            degrees = 90
        else:
            try:
                degrees = int(body.get("degrees") or request.POST.get("degrees") or 0)
            except (TypeError, ValueError):
                return _json_error("Indiquez left, right, ou degrees (±90).")
            if degrees not in (-90, 90, -180, 180, -270, 270):
                return _json_error("Rotation invalide (multiples de ±90°).")
        try:
            angle = rotate_pdf_page(source.pdf_path, page, degrees)
        except ValueError as exc:
            return _json_error(str(exc))
        source.invalidate_thumb(page)
        return JsonResponse({"ok": True, "page": page, "rotate": angle})


class StaffPieceDecoupeCommitView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        from django.contrib import messages

        from repertoire.views import _save_part_pdf

        piece = get_object_or_404(Piece, slug=slug)
        source = split_store.load_from_session(request.session, piece.pk)
        if source is None:
            return _json_error(
                "Aucun PDF source. Rechargez un fichier.", status=404
            )
        body = _parse_json_body(request)
        ranges, err = validate_split_ranges(
            body.get("ranges") or [], source.page_count
        )
        if err:
            return _json_error(err)
        assert ranges is not None
        created: list[str] = []
        labels = dict(PartPoste.choices)
        with transaction.atomic():
            for item in ranges:
                data = extract_pdf_pages_bytes(
                    source.pdf_path, item["start"], item["end"]
                )
                filename = f"{slugify(piece.title)}-{item['poste']}.pdf"
                _save_part_pdf(
                    piece,
                    item["poste"],
                    data,
                    filename,
                    source_name=(
                        f"{source.source_name} p.{item['start']}-{item['end']}"
                    ),
                )
                created.append(labels.get(item["poste"], item["poste"]))
        if not body.get("keep_source"):
            split_store.clear_session(request.session, piece.pk)
        messages.success(
            request,
            f"{len(created)} partition(s) enregistrée(s) : "
            + ", ".join(created)
            + ".",
        )
        return JsonResponse(
            {
                "ok": True,
                "redirect": reverse("repertoire:staff_piece_edit", args=[slug]),
                "count": len(created),
            }
        )


class StaffPieceDecoupeClearView(PlanningStaffRequiredMixin, View):
    def post(self, request, slug: str):
        piece = get_object_or_404(Piece, slug=slug)
        split_store.clear_session(request.session, piece.pk)
        if request.content_type and "application/json" in request.content_type:
            return JsonResponse({"ok": True})
        return redirect("repertoire:staff_piece_decoupe", slug=slug)
