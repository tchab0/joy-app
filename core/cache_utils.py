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
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, "is_authenticated", False):
                return view_func(request, *args, **kwargs)
            prefix = key_prefix() if callable(key_prefix) else key_prefix
            return cache_page(timeout, key_prefix=prefix)(view_func)(request, *args, **kwargs)

        return _wrapped

    return decorator
