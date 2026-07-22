"""Middleware de collecte d’usage (public + espaces authentifiés)."""

from __future__ import annotations


class UsageTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if 200 <= response.status_code < 400:
                from stats.tracking import record_request_usage

                record_request_usage(request, response)
        except Exception:
            # Jamais bloquer la réponse métier pour de la télémétrie.
            pass
        return response
