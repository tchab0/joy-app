import json
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import F
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from events.models import Event
from events.share_image import get_or_create_og_image

SHARE_NETWORKS = {
    "facebook": "shares_facebook",
    "instagram": "shares_instagram",
    "bluesky": "shares_bluesky",
}


def _share_request_allowed(request) -> bool:
    """Accepte same-origin (Origin/Referer) — endpoint csrf_exempt (pages publiques cachées)."""
    allowed = {h.lower() for h in settings.ALLOWED_HOSTS if h and h != "*"}
    origin = request.META.get("HTTP_ORIGIN") or ""
    referer = request.META.get("HTTP_REFERER") or ""
    if origin:
        host = (urlparse(origin).hostname or "").lower()
        return host in allowed
    if referer:
        host = (urlparse(referer).hostname or "").lower()
        return host in allowed
    # Pas d'Origin/Referer (certains navigateurs) : Host suffit
    host = (request.get_host() or "").split(":")[0].lower()
    return host in allowed


@require_GET
@cache_control(public=True, max_age=3600)
def concert_og_image(request, slug):
    """JPEG Open Graph 1200×630 pour un concert public."""
    event = get_object_or_404(
        Event.objects.select_related("venue", "parent"),
        slug=slug,
        public=True,
    )
    if not event.slug:
        raise Http404
    path = get_or_create_og_image(event)
    as_attachment = request.GET.get("download") in ("1", "true", "yes")
    if as_attachment:
        return FileResponse(
            path.open("rb"),
            content_type="image/jpeg",
            as_attachment=True,
            filename=f"joy-{event.slug}.jpg",
        )
    return FileResponse(path.open("rb"), content_type="image/jpeg")


@csrf_exempt
@require_POST
def concert_share_track(request, slug):
    """Incrémente le compteur de partages pour un réseau (facebook|instagram|bluesky)."""
    if not _share_request_allowed(request):
        return JsonResponse({"ok": False, "error": "origine refusée"}, status=403)

    event = get_object_or_404(Event, slug=slug, public=True)
    network = ""
    if request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        network = (payload.get("network") or "").strip().lower()
    else:
        network = (request.POST.get("network") or "").strip().lower()

    field = SHARE_NETWORKS.get(network)
    if not field:
        return JsonResponse({"ok": False, "error": "réseau invalide"}, status=400)

    Event.objects.filter(pk=event.pk).update(**{field: F(field) + 1})
    event.refresh_from_db(fields=list(SHARE_NETWORKS.values()))
    return JsonResponse(
        {
            "ok": True,
            "network": network,
            "counts": {
                "facebook": event.shares_facebook,
                "instagram": event.shares_instagram,
                "bluesky": event.shares_bluesky,
            },
        }
    )
