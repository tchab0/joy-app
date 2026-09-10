from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class SeoStaticPagesTests(TestCase):
    def test_prestations_page_ok(self):
        r = self.client.get(reverse("prestations"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Prestations")
        self.assertContains(r, 'name="description"')
        self.assertContains(r, "application/ld+json")
        self.assertContains(r, "Service")
        self.assertContains(r, reverse("contact") + "?mode=prestation")

    def test_robots_disallows_private_areas(self):
        r = self.client.get(reverse("robots_txt"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Disallow: /stats/", body)
        self.assertIn("Disallow: /planning/", body)
        self.assertIn("Sitemap:", body)

    def test_sitemap_includes_prestations(self):
        r = self.client.get(reverse("django.contrib.sitemaps.views.sitemap"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "/prestations/")


@override_settings(
    SITE_URL="https://example.test",
    SOCIAL_FACEBOOK_URL="https://www.facebook.com/jazzorchestrayonnais",
    SOCIAL_LINKABAND_URL="https://linkaband.com/jazz-orchestra-yonnais",
    SOCIAL_INSTAGRAM_URL="https://www.instagram.com/example/",
    ORG_TELEPHONE="+33200000000",
)
class SeoJsonLdTests(SimpleTestCase):
    def test_music_group_includes_logo_same_as_and_phone(self):
        from core.seo import music_group_jsonld

        data = music_group_jsonld()
        self.assertEqual(data["@type"], "MusicGroup")
        self.assertIn("logo", data)
        self.assertEqual(data["telephone"], "+33200000000")
        self.assertIn("https://www.instagram.com/example/", data["sameAs"])
        self.assertIn("https://linkaband.com/jazz-orchestra-yonnais", data["sameAs"])
        self.assertEqual(data["address"]["postalCode"], "85000")

    def test_service_jsonld(self):
        from core.seo import service_jsonld

        data = service_jsonld()
        self.assertEqual(data["@type"], "Service")
        self.assertIn("/prestations/", data["url"])
