"""Blocage de la navigation tant qu’un mot de passe provisoire n’est pas changé."""

from __future__ import annotations

from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.urls import reverse

# Vues accessibles avec un mot de passe provisoire (sinon : boucle de redirection).
ALLOWED_URL_NAMES = frozenset(
    {
        "account_password_change",
        "account_login",
        "account_login_otp",
        "account_login_2fa",
        "account_logout",
    }
)

ALLOWED_PREFIXES = ("/static/", "/media/", "/admin/logout/")


def _wants_json(request) -> bool:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


class ForcePasswordChangeMiddleware:
    """Redirige vers « Nouveau mot de passe » si ``user.must_change_password``.

    ``process_view`` (et non ``__call__``) pour disposer de ``resolver_match``
    et raisonner sur les noms d’URL plutôt que sur des chemins en dur.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        if not getattr(user, "must_change_password", False):
            return None

        match = request.resolver_match
        if match is not None and match.url_name in ALLOWED_URL_NAMES:
            return None
        if request.path.startswith(ALLOWED_PREFIXES):
            return None

        target = reverse("account_password_change")
        if _wants_json(request):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "mot_de_passe_provisoire",
                    "url": target,
                },
                status=403,
            )
        return redirect_to_login(request.get_full_path(), login_url=target)
