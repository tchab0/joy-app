from django.http import HttpResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_http_methods

from .seo import site_url


@require_http_methods(["GET", "HEAD"])
@cache_page(3600)
def robots_txt(request):
    base = site_url()
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /compte/",
        "Disallow: /planning/",
        "Disallow: /repertoire/",
        "Disallow: /chat/",
        "Disallow: /admin/",
        "Disallow: /admin-",
        "Disallow: /feedback/",
        "Disallow: /medias/proposer/",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")
