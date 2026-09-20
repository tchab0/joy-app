"""Icônes PWA / Web Push — cache-bust."""

from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from users.pwa_icons import (
    absolute_icon_192,
    icon_192_path,
    icon_content_version,
    inject_sw_icon_version,
)


class PwaIconVersionTests(SimpleTestCase):
    def test_icon_path_includes_content_hash(self):
        version = icon_content_version()
        self.assertTrue(version)
        self.assertIn(f"v={version}", icon_192_path())
        self.assertIn(version, absolute_icon_192())

    def test_sw_placeholder_is_replaced(self):
        version = icon_content_version()
        out = inject_sw_icon_version(
            'icon: "/static/users/icons/icon-192.png?v=__JOY_ICON_VERSION__"'
        )
        self.assertIn(f"v={version}", out)
        self.assertNotIn("__JOY_ICON_VERSION__", out)


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost"],
)
class ServiceWorkerIconTests(SimpleTestCase):
    def test_service_worker_serves_versioned_icon(self):
        client = Client()
        r = client.get(reverse("service_worker"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertNotIn("__JOY_ICON_VERSION__", body)
        self.assertIn(f"icon-192.png?v={icon_content_version()}", body)

    def test_manifest_icons_are_versioned(self):
        client = Client()
        r = client.get(reverse("web_manifest"))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        version = icon_content_version()
        self.assertTrue(
            any(version in icon.get("src", "") for icon in data.get("icons", []))
        )
