from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils import timezone

from events.models import Event

from .seo import STATIC_PUBLIC_PATHS


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    protocol = "https"

    def items(self):
        return list(STATIC_PUBLIC_PATHS)

    def location(self, item):
        name, kwargs = item
        return reverse(name, kwargs=kwargs)

    def priority(self, item):
        name, _ = item
        return {
            "home": 1.0,
            "concerts": 0.9,
            "medias": 0.8,
            "contact": 0.8,
        }.get(name, 0.6)


class ConcertSitemap(Sitemap):
    changefreq = "weekly"
    protocol = "https"

    def items(self):
        return (
            Event.objects.filter(public=True)
            .exclude(slug="")
            .order_by("-date_debut")
        )

    def lastmod(self, obj):
        return obj.date_debut

    def location(self, obj):
        return obj.get_absolute_url()

    def priority(self, obj):
        if obj.date_debut >= timezone.now():
            return 0.9
        return 0.5
