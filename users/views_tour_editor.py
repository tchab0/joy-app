"""Éditeur graphique des guides (coach marks) — réservé au staff."""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import OperationalError, ProgrammingError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from users.tour_anchors import TOUR_ANCHORS, TOUR_PAGE_PATHS
from users.tour_defaults import MUSICIAN_STEPS, STAFF_STEPS
from users.tour_models import ProductTour, ProductTourStep

logger = logging.getLogger(__name__)

_DEFAULTS = {
    ProductTour.Audience.MUSICIAN: ("Guide musicien", MUSICIAN_STEPS),
    ProductTour.Audience.STAFF: ("Guide staff", STAFF_STEPS),
}


def _ensure_tours() -> list[ProductTour]:
    """Crée les tours manquants à partir des défauts (tolère schéma absent)."""
    tours: list[ProductTour] = []
    try:
        for audience, (title, steps) in _DEFAULTS.items():
            tour, created = ProductTour.objects.get_or_create(
                audience=audience,
                defaults={"title": title, "version": 1, "is_active": True},
            )
            if created or not tour.steps.exists():
                if not tour.steps.exists():
                    ProductTourStep.objects.bulk_create(
                        [
                            ProductTourStep(
                                tour=tour,
                                order=s["order"],
                                anchor=s.get("anchor") or "",
                                title=s["title"],
                                body=s["body"],
                                page_path=s.get("page_path") or "",
                                open_mobile_nav=bool(s.get("open_mobile_nav")),
                                scroll_footer=bool(s.get("scroll_footer")),
                                is_active=True,
                            )
                            for s in steps
                        ]
                    )
            tours.append(tour)
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Éditeur guides indisponible (schéma) : %s", exc)
        return []
    return tours


def _serialize_step(step: ProductTourStep) -> dict:
    return {
        "id": step.pk,
        "order": step.order,
        "anchor": step.anchor or "",
        "title": step.title,
        "body": step.body,
        "page_path": step.page_path or "",
        "open_mobile_nav": bool(step.open_mobile_nav),
        "scroll_footer": bool(step.scroll_footer),
        "is_active": bool(step.is_active),
    }


def _serialize_tour(tour: ProductTour) -> dict:
    steps = [_serialize_step(s) for s in tour.steps.all().order_by("order", "pk")]
    return {
        "id": tour.pk,
        "audience": tour.audience,
        "audience_label": tour.get_audience_display(),
        "title": tour.title,
        "version": tour.version,
        "is_active": bool(tour.is_active),
        "steps": steps,
    }


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@staff_member_required
@require_http_methods(["GET"])
def admin_tours(request: HttpRequest) -> HttpResponse:
    tours = _ensure_tours()
    if not tours:
        messages.error(
            request,
            "Les guides ne sont pas disponibles (migration manquante ?).",
        )
        return redirect("home")

    payload = {
        "tours": {t.audience: _serialize_tour(t) for t in tours},
        "anchors": [{"value": v, "label": lab} for v, lab in TOUR_ANCHORS],
        "page_paths": [{"value": v, "label": lab} for v, lab in TOUR_PAGE_PATHS],
        "save_url": reverse("admin_tours_save"),
        "csrf_token": request.META.get("CSRF_COOKIE") or "",
    }
    # Prefer request CSRF for form posts
    from django.middleware.csrf import get_token

    payload["csrf_token"] = get_token(request)

    audience = (request.GET.get("audience") or "musician").strip().lower()
    if audience not in payload["tours"]:
        audience = "musician"

    return render(
        request,
        "users/admin_tours.html",
        {
            "tour_editor_config": payload,
            "initial_audience": audience,
        },
    )


@staff_member_required
@require_POST
def admin_tours_save(request: HttpRequest) -> JsonResponse:
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON invalide."}, status=400)

    audience = (data.get("audience") or "").strip().lower()
    if audience not in {c.value for c in ProductTour.Audience}:
        return JsonResponse({"ok": False, "error": "Audience invalide."}, status=400)

    title = (data.get("title") or "").strip()[:120]
    if not title:
        return JsonResponse({"ok": False, "error": "Titre requis."}, status=400)

    try:
        version = max(1, int(data.get("version") or 1))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Version invalide."}, status=400)

    bump = _parse_bool(data.get("bump_version"))
    is_active = _parse_bool(data.get("is_active", True))
    steps_in = data.get("steps")
    if not isinstance(steps_in, list):
        return JsonResponse({"ok": False, "error": "Étapes invalides."}, status=400)

    cleaned: list[dict] = []
    for i, raw in enumerate(steps_in):
        if not isinstance(raw, dict):
            return JsonResponse(
                {"ok": False, "error": f"Étape {i + 1} invalide."}, status=400
            )
        st_title = (raw.get("title") or "").strip()[:160]
        st_body = (raw.get("body") or "").strip()
        if not st_title:
            return JsonResponse(
                {"ok": False, "error": f"Étape {i + 1} : titre requis."},
                status=400,
            )
        if not st_body:
            return JsonResponse(
                {"ok": False, "error": f"Étape {i + 1} : texte requis."},
                status=400,
            )
        cleaned.append(
            {
                "anchor": (raw.get("anchor") or "").strip()[:64],
                "title": st_title,
                "body": st_body,
                "page_path": (raw.get("page_path") or "").strip()[:200],
                "open_mobile_nav": _parse_bool(raw.get("open_mobile_nav")),
                "scroll_footer": _parse_bool(raw.get("scroll_footer")),
                "is_active": _parse_bool(raw.get("is_active", True)),
            }
        )

    try:
        with transaction.atomic():
            tour, _ = ProductTour.objects.get_or_create(
                audience=audience,
                defaults={"title": title, "version": version, "is_active": is_active},
            )
            if bump:
                version = max(version, tour.version) + 1
            tour.title = title
            tour.version = version
            tour.is_active = is_active
            tour.save(update_fields=["title", "version", "is_active"])

            # Remplace les étapes (ordre = index + 1)
            tour.steps.all().delete()
            ProductTourStep.objects.bulk_create(
                [
                    ProductTourStep(
                        tour=tour,
                        order=idx + 1,
                        anchor=s["anchor"],
                        title=s["title"],
                        body=s["body"],
                        page_path=s["page_path"],
                        open_mobile_nav=s["open_mobile_nav"],
                        scroll_footer=s["scroll_footer"],
                        is_active=s["is_active"],
                    )
                    for idx, s in enumerate(cleaned)
                ]
            )
            tour.refresh_from_db()
            # Prefetch steps for response
            tour = (
                ProductTour.objects.filter(pk=tour.pk)
                .prefetch_related("steps")
                .get()
            )
    except (ProgrammingError, OperationalError) as exc:
        logger.warning("Sauvegarde guide échouée (schéma) : %s", exc)
        return JsonResponse(
            {"ok": False, "error": "Schéma indisponible."}, status=503
        )

    return JsonResponse({"ok": True, "tour": _serialize_tour(tour)})
