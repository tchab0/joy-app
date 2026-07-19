"""Vues Web Push : abonnement, service worker, manifest PWA."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .models import PushSubscription
from .webpush import vapid_configured, vapid_public_key

logger = logging.getLogger(__name__)

_SW_PATH = settings.BASE_DIR / "users" / "static" / "users" / "sw.js"


@require_GET
def service_worker(request: HttpRequest) -> HttpResponse:
    """Service worker à la racine pour un scope « / »."""
    if not _SW_PATH.is_file():
        return HttpResponse("// missing sw.js", status=404, content_type="application/javascript")
    resp = FileResponse(_SW_PATH.open("rb"), content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


@require_GET
def web_manifest(request: HttpRequest) -> HttpResponse:
    data = {
        "name": "Jazz Orchestra Yonnais",
        "short_name": "JOY",
        "description": "Planning, chat et alertes de l’orchestre",
        "start_url": "/compte/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f5f2ec",
        "theme_color": "#1a1714",
        "lang": "fr",
        "icons": [
            {
                "src": "/static/users/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/static/users/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return HttpResponse(
        json.dumps(data, ensure_ascii=False),
        content_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@require_GET
@login_required
def push_vapid_public_key(request: HttpRequest) -> JsonResponse:
    if not vapid_configured():
        return JsonResponse({"ok": False, "error": "push_disabled"}, status=503)
    return JsonResponse({"ok": True, "publicKey": vapid_public_key()})


@login_required
@require_http_methods(["POST", "DELETE"])
@ensure_csrf_cookie
def push_subscription(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "json_invalide"}, status=400)

    endpoint = (payload.get("endpoint") or "").strip()
    if not endpoint:
        return JsonResponse({"ok": False, "error": "endpoint_requis"}, status=400)

    if request.method == "DELETE":
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return JsonResponse({"ok": True})

    keys = payload.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not p256dh or not auth:
        return JsonResponse({"ok": False, "error": "cles_requises"}, status=400)

    ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    sub, _created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": ua,
        },
    )
    # Si un autre user avait cet endpoint, update_or_create avec endpoint unique
    # l’a réassigné — OK (un endpoint = un appareil).
    if sub.user_id != request.user.pk:
        sub.user = request.user
        sub.save(update_fields=["user", "updated_at"])

    return JsonResponse({"ok": True, "id": sub.pk})


@login_required
@require_GET
def push_status(request: HttpRequest) -> JsonResponse:
    count = PushSubscription.objects.filter(user=request.user).count()
    return JsonResponse(
        {
            "ok": True,
            "configured": vapid_configured(),
            "subscriptions": count,
        }
    )
