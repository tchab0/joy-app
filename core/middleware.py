"""Ajoute X-Robots-Tag: noindex sur les zones privées."""

from .seo import path_should_noindex


class NoIndexPrivateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if path_should_noindex(request.path):
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response
