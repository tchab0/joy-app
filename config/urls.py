from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("compte/", include("users.urls")),
    path("", include("feedback.urls")),
    path("", include("core.urls")),
    path("concerts/", include("events.urls")),
    path("planning/", include("planning.urls")),
    path("chat/", include("chat.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls
    urlpatterns += debug_toolbar_urls()
