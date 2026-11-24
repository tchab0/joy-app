"""Middlewares HTTP transverses (SEO, anti-double-soumission)."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse

from core.ratelimit import claim_mutating_request
from core.seo import path_should_noindex

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Endpoints où un retry immédiat est légitime (auth, OTP, lecture seule…).
_DEDUPE_EXEMPT_PREFIXES = (
    "/compte/login",
    "/compte/logout",
    "/compte/otp",
    "/compte/2fa",
    "/compte/password",
    "/admin/login",
    "/admin/logout",
)


class NoIndexPrivateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if path_should_noindex(request.path):
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response


class DenyDuplicateSubmitMiddleware:
    """
    Bloque les POST/PUT/PATCH/DELETE authentifiés identiques répétés
    dans une courte fenêtre (double-clic, retry impatient).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_dedupe(request) and not claim_mutating_request(request):
            return self._duplicate_response(request)
        return self.get_response(request)

    def _should_dedupe(self, request) -> bool:
        if request.method not in _MUTATING:
            return False
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        path = request.path or "/"
        return not any(path.startswith(p) for p in _DEDUPE_EXEMPT_PREFIXES)

    def _wants_json(self, request) -> bool:
        content_type = (request.content_type or "").lower()
        if "json" in content_type:
            return True
        accept = (request.META.get("HTTP_ACCEPT") or "").lower()
        if "application/json" in accept and "text/html" not in accept:
            return True
        requested = (request.META.get("HTTP_X_REQUESTED_WITH") or "").lower()
        return requested == "xmlhttprequest"

    def _duplicate_response(self, request):
        msg = "Action déjà prise en compte (double envoi évité)."
        if self._wants_json(request):
            return JsonResponse({"ok": False, "error": msg, "duplicate": True}, status=409)
        messages.warning(request, msg)
        referer = request.META.get("HTTP_REFERER") or "/"
        return HttpResponseRedirect(referer)
