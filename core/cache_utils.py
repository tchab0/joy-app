"""Helpers cache pour pages publiques dont la nav dépend de l’auth."""

from functools import wraps

from django.views.decorators.cache import cache_page


def cache_page_anonymous(timeout):
    """Met en cache la réponse HTML uniquement pour les visiteurs anonymes.

    Évite qu’une navigation musicien/staff (Chat, Coulisses, Contact masqué)
    pollue le cache servi au public.
    """

    def decorator(view_func):
        cached_view = cache_page(timeout)(view_func)

        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, "is_authenticated", False):
                return view_func(request, *args, **kwargs)
            return cached_view(request, *args, **kwargs)

        return _wrapped

    return decorator
