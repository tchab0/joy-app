from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core.sitemaps import ConcertSitemap, StaticViewSitemap
from core.views_seo import robots_txt
from users import views_push

sitemaps = {
    "static": StaticViewSitemap,
    "concerts": ConcertSitemap,
}

urlpatterns = [
    path("admin/", admin.site.urls),
    path("robots.txt", robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("sw.js", views_push.service_worker, name="service_worker"),
    path("manifest.webmanifest", views_push.web_manifest, name="web_manifest"),
    path("compte/", include("users.urls")),
    path("", include("feedback.urls")),
    path("", include("core.urls")),
    path("concerts/", include("events.urls")),
    path("planning/", include("planning.urls")),
    path("chat/", include("chat.urls")),
    path("repertoire/", include("repertoire.urls")),
    path("stats/", include("stats.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls
    urlpatterns += debug_toolbar_urls()
