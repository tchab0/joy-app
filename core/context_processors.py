from django.conf import settings

from .seo import path_should_noindex, site_url


def seo(request):
    return {
        "SITE_URL": site_url(),
        "SEO_NOINDEX": path_should_noindex(request.path),
        "GOOGLE_SITE_VERIFICATION": getattr(settings, "GOOGLE_SITE_VERIFICATION", ""),
        "GA_MEASUREMENT_ID": getattr(settings, "GA_MEASUREMENT_ID", ""),
    }
