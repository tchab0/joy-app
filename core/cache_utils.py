"""Helpers cache pour pages publiques dont la nav dépend de l’auth."""

from functools import wraps

from django.views.decorators.cache import cache_page


def cache_page_anonymous(timeout, key_prefix=""):
    """Met en cache la réponse HTML uniquement pour les visiteurs anonymes.

    Évite qu’une navigation musicien/staff (Coulisses, Contact masqué)
    pollue le cache servi au public.

    key_prefix peut être une chaîne ou un callable (ex. version CMS).
    """

    def decorator(view_func):
        cached_view = cache_page(timeout, key_prefix=key_prefix)(view_func)

        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, "is_authenticated", False):
                return view_func(request, *args, **kwargs)
            # ``cache_page`` accepts a static key prefix. Recrée le décorateur
            # pour les rares préfixes versionnés (ex. page d'accueil).
            if callable(key_prefix):
                response = cache_page(timeout, key_prefix=key_prefix())(
                    view_func
                )(request, *args, **kwargs)
            else:
                response = cached_view(request, *args, **kwargs)
            if not getattr(request, "_cache_update_cache", True):
                response["X-JOY-Page-Cache"] = "HIT"
            return response

        return _wrapped

    return decorator
