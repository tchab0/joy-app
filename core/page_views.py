"""Éditeur de pages publiques (staff) — cartes ordonables."""

from __future__ import annotations

import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import MediaItem, PageBlock, SitePage
from .page_cms import (
    bump_home_cache,
    default_contenu,
    serialize_block,
    youtube_video_id,
)

logger = logging.getLogger(__name__)

ALLOWED_BLOCK_TYPES = {c[0] for c in PageBlock.TYPE_CHOICES}


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_json(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


def _touch_page(page: SitePage) -> None:
    page.updated_at = timezone.now()
    page.save(update_fields=["updated_at"])
    if page.slug == "accueil":
        bump_home_cache()


def _sanitize_contenu(block_type: str, data: dict) -> dict:
    data = data or {}
    if block_type == PageBlock.TYPE_HERO:
        return {
            "title_accent": str(data.get("title_accent") or "")[:80],
            "title": str(data.get("title") or "")[:200],
            "tag": str(data.get("tag") or "")[:120],
            "subtitle": str(data.get("subtitle") or "")[:500],
            "image_alt": str(data.get("image_alt") or "")[:200],
            "image_static": str(data.get("image_static") or "")[:200],
            "image_url": str(data.get("image_url") or "")[:500],
            "video_url": str(data.get("video_url") or "")[:500],
        }
    if block_type == PageBlock.TYPE_TEXT:
        return {
            "titre": str(data.get("titre") or "")[:200],
            "body": str(data.get("body") or "")[:20000],
            "cta_label": str(data.get("cta_label") or "")[:80],
            "cta_url": str(data.get("cta_url") or "")[:500],
        }
    if block_type == PageBlock.TYPE_IMAGE:
        return {
            "image_alt": str(data.get("image_alt") or "")[:200],
            "caption": str(data.get("caption") or "")[:300],
            "image_url": str(data.get("image_url") or "")[:500],
        }
    if block_type == PageBlock.TYPE_VIDEO:
        url = str(data.get("video_url") or "")[:500]
        # Accepte URL complète ou id YouTube
        if url and not youtube_video_id(url) and "://" not in url:
            pass
        return {
            "titre": str(data.get("titre") or "")[:200],
            "video_url": url,
        }
    if block_type == PageBlock.TYPE_CONCERTS:
        try:
            limit = int(data.get("limit") or 3)
        except (TypeError, ValueError):
            limit = 3
        return {
            "titre": str(data.get("titre") or "Prochains concerts")[:200],
            "limit": max(1, min(limit, 12)),
        }
    return {}


@staff_member_required
def admin_pages(request):
    pages = SitePage.objects.prefetch_related("blocks").order_by("titre")
    return render(request, "core/admin_pages.html", {"pages": pages})


@staff_member_required
def admin_page_edit(request, slug):
    page = get_object_or_404(SitePage.objects.prefetch_related("blocks"), slug=slug)
    if request.method == "POST" and request.POST.get("action") == "meta":
        page.titre = (request.POST.get("titre") or page.titre)[:200]
        page.meta_description = (request.POST.get("meta_description") or "")[:320]
        page.publie = request.POST.get("publie") == "on"
        page.save()
        _touch_page(page)
        return redirect("admin_page_edit", slug=page.slug)

    blocks = list(page.blocks.select_related("media").order_by("ordre", "id"))
    blocks_json = [serialize_block(b) for b in blocks]
    return render(
        request,
        "core/admin_page_edit.html",
        {
            "page": page,
            "blocks": blocks,
            "blocks_json": blocks_json,
            "block_types": PageBlock.TYPE_CHOICES,
        },
    )


@staff_member_required
@require_POST
def admin_page_block_create(request, slug):
    page = get_object_or_404(SitePage, slug=slug)
    payload = _parse_json(request)
    block_type = payload.get("type") or request.POST.get("type")
    if block_type not in ALLOWED_BLOCK_TYPES:
        return _json_error("Type de bloc invalide")
    max_ordre = page.blocks.order_by("-ordre").values_list("ordre", flat=True).first()
    ordre = (max_ordre or 0) + 1
    titre_admin = (payload.get("titre_admin") or "")[:120]
    block = PageBlock.objects.create(
        page=page,
        type=block_type,
        titre_admin=titre_admin,
        ordre=ordre,
        visible=True,
        contenu=default_contenu(block_type),
    )
    _touch_page(page)
    return JsonResponse({"ok": True, "block": serialize_block(block)})


@staff_member_required
@require_http_methods(["POST", "PATCH", "PUT"])
def admin_page_block_update(request, slug, pk):
    page = get_object_or_404(SitePage, slug=slug)
    block = get_object_or_404(PageBlock.objects.select_related("media"), page=page, pk=pk)
    payload = _parse_json(request)

    if "titre_admin" in payload:
        block.titre_admin = str(payload.get("titre_admin") or "")[:120]
    if "visible" in payload:
        block.visible = bool(payload.get("visible"))
    if "contenu" in payload and isinstance(payload["contenu"], dict):
        block.contenu = _sanitize_contenu(block.type, payload["contenu"])
    if "media_id" in payload:
        mid = payload.get("media_id")
        if mid in (None, "", 0, "0"):
            block.media = None
            contenu = dict(block.contenu or {})
            if block.type in (PageBlock.TYPE_IMAGE, PageBlock.TYPE_HERO):
                contenu["image_url"] = ""
                contenu["image_static"] = ""
            if block.type == PageBlock.TYPE_VIDEO:
                contenu["video_url"] = ""
            block.contenu = _sanitize_contenu(block.type, contenu)
        else:
            try:
                media = MediaItem.objects.get(pk=int(mid))
            except (MediaItem.DoesNotExist, TypeError, ValueError):
                return _json_error("Média introuvable")
            block.media = media
            # Recopie l’URL affichable dans contenu pour prévisualisation
            url = media.url_affichage or (
                media.fichier_actif.url if media.fichier_actif else ""
            )
            contenu = dict(block.contenu or {})
            if block.type in (PageBlock.TYPE_IMAGE, PageBlock.TYPE_HERO):
                if url:
                    contenu["image_url"] = url
                    contenu["image_static"] = ""
            if block.type == PageBlock.TYPE_VIDEO:
                if media.url_externe:
                    contenu["video_url"] = media.url_externe
                elif url:
                    contenu["video_url"] = url
            block.contenu = _sanitize_contenu(block.type, contenu)

    block.save()
    _touch_page(page)
    block = PageBlock.objects.select_related("media").get(pk=block.pk)
    return JsonResponse({"ok": True, "block": serialize_block(block)})


@staff_member_required
@require_http_methods(["POST", "DELETE"])
def admin_page_block_delete(request, slug, pk):
    page = get_object_or_404(SitePage, slug=slug)
    block = get_object_or_404(PageBlock, page=page, pk=pk)
    if request.method == "POST" and _parse_json(request).get("action") not in (
        "delete",
        None,
        "",
    ):
        # POST sans action delete : ignore sauf DELETE method
        if request.POST.get("action") != "delete":
            pass
    block.delete()
    _touch_page(page)
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def admin_page_reorder(request, slug):
    page = get_object_or_404(SitePage, slug=slug)
    payload = _parse_json(request)
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return _json_error("Liste d’ids requise")
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        return _json_error("Ids invalides")

    blocks = {b.pk: b for b in page.blocks.filter(pk__in=ids)}
    if len(blocks) != len(set(ids)):
        return _json_error("Un ou plusieurs blocs sont introuvables")

    for index, pk in enumerate(ids):
        block = blocks[pk]
        if block.ordre != index:
            block.ordre = index
            block.save(update_fields=["ordre"])
    _touch_page(page)
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def admin_page_upload(request, slug):
    """Téléverse une image ; lie à un bloc existant ou crée une carte Image."""
    page = get_object_or_404(SitePage, slug=slug)
    uploaded = request.FILES.get("fichier") or request.FILES.get("file")
    if not uploaded:
        return _json_error("Fichier manquant")

    name = (uploaded.name or "").lower()
    if not any(name.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return _json_error("Formats acceptés : JPG, PNG, GIF, WebP")

    titre = (request.POST.get("titre") or uploaded.name or "Image page")[:200]
    media = MediaItem.objects.create(
        type="photo",
        titre=titre,
        fichier=uploaded,
        publie=True,
        statut="publie",
        soumis_par_nom=request.user.get_full_name() or request.user.get_username(),
        soumis_par_email=getattr(request.user, "email", "") or "",
    )

    block = None
    block_id = request.POST.get("block_id")
    create_block = request.POST.get("create_block") in ("1", "true", "on", "yes")

    if block_id:
        try:
            block = PageBlock.objects.get(page=page, pk=int(block_id))
        except (PageBlock.DoesNotExist, ValueError, TypeError):
            block = None

    if create_block and block is None:
        max_ordre = page.blocks.order_by("-ordre").values_list("ordre", flat=True).first()
        block = PageBlock.objects.create(
            page=page,
            type=PageBlock.TYPE_IMAGE,
            titre_admin=titre[:120],
            ordre=(max_ordre or 0) + 1,
            visible=True,
            contenu=default_contenu(PageBlock.TYPE_IMAGE),
        )

    block_payload = None
    if block and block.type in (PageBlock.TYPE_IMAGE, PageBlock.TYPE_HERO):
        block.media = media
        contenu = dict(block.contenu or {})
        contenu["image_url"] = media.fichier.url if media.fichier else ""
        contenu["image_static"] = ""
        if not contenu.get("image_alt"):
            contenu["image_alt"] = titre
        if block.type == PageBlock.TYPE_IMAGE and not block.titre_admin:
            block.titre_admin = titre[:120]
        block.contenu = _sanitize_contenu(block.type, contenu)
        block.save()
        block_payload = serialize_block(
            PageBlock.objects.select_related("media").get(pk=block.pk)
        )
        _touch_page(page)

    return JsonResponse(
        {
            "ok": True,
            "media": {
                "id": media.pk,
                "titre": media.titre,
                "type": media.type,
                "url": media.fichier.url if media.fichier else "",
                "url_externe": media.url_externe or "",
            },
            "block": block_payload,
        }
    )


@staff_member_required
@require_GET
def admin_page_media_picker(request):
    q = (request.GET.get("q") or "").strip()
    media_type = (request.GET.get("type") or "photo").strip()
    if media_type not in ("photo", "video", "all"):
        media_type = "photo"

    qs = MediaItem.objects.filter(publie=True).order_by("-soumis_le")
    if media_type != "all":
        qs = qs.filter(type=media_type)
    else:
        qs = qs.filter(type__in=("photo", "video"))
    if q:
        qs = qs.filter(titre__icontains=q)

    items = []
    for m in qs[:48]:
        url = m.url_affichage or (m.fichier_actif.url if m.fichier_actif else "")
        if m.type == "video" and not url and m.url_externe:
            url = m.url_externe
        if not url and not m.url_externe:
            continue
        items.append(
            {
                "id": m.pk,
                "titre": m.titre,
                "url": url or "",
                "url_externe": m.url_externe or "",
                "type": m.type,
            }
        )
    return JsonResponse({"ok": True, "items": items})
