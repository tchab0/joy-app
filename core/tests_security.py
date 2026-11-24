from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core import ratelimit
from core.safe_redirect import is_safe_local_path

User = get_user_model()


class SafeRedirectTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/", HTTP_HOST="testserver")

    def test_accepts_local_paths(self):
        self.assertTrue(is_safe_local_path("/planning/", self.request))
        self.assertTrue(is_safe_local_path("/planning/?vue=mois#j", self.request))

    def test_rejects_external_targets(self):
        for url in ("", "//evil.com", "/\\evil.com", "https://evil.com/", "planning/", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertFalse(is_safe_local_path(url, self.request))


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_consume_blocks_after_limit(self):
        for _ in range(3):
            self.assertTrue(ratelimit.consume("t", "ip", 3, 60))
        self.assertFalse(ratelimit.consume("t", "ip", 3, 60))
        ratelimit.reset("t", "ip")
        self.assertTrue(ratelimit.consume("t", "ip", 3, 60))

    def test_claim_once_blocks_duplicates(self):
        self.assertTrue(ratelimit.claim_once("propose", "u1:titre", 60))
        self.assertFalse(ratelimit.claim_once("propose", "u1:titre", 60))
        self.assertTrue(ratelimit.claim_once("propose", "u1:autre", 60))
        ratelimit.reset("propose", "u1:titre")
        self.assertTrue(ratelimit.claim_once("propose", "u1:titre", 60))

    def test_claim_notify_once_blocks_same_payload(self):
        self.assertTrue(
            ratelimit.claim_notify_once(
                related_type="staff_alert",
                related_id=42,
                title="JOY — Présence annulée",
                body="Alice absente",
            )
        )
        self.assertFalse(
            ratelimit.claim_notify_once(
                related_type="staff_alert",
                related_id=42,
                title="JOY — Présence annulée",
                body="Alice absente",
            )
        )
        self.assertTrue(
            ratelimit.claim_notify_once(
                related_type="staff_alert",
                related_id=42,
                title="JOY — Présence annulée",
                body="Alice absente avec motif",
            )
        )

    def test_client_ip_prefers_nginx_header(self):
        request = RequestFactory().get("/", HTTP_X_REAL_IP="203.0.113.7", REMOTE_ADDR="")
        self.assertEqual(ratelimit.client_ip(request), "203.0.113.7")


class DenyDuplicateSubmitMiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="dedupe", password="pass12345", is_musician=True
        )

    def test_identical_post_returns_409_for_json(self):
        self.client.login(username="dedupe", password="pass12345")
        body = '{"response":"no"}'
        # Middleware tourne avant la vue : 1er POST passe, 2e identique → 409.
        r1 = self.client.post(
            "/planning/participations/999999/respond/",
            body,
            content_type="application/json",
        )
        r2 = self.client.post(
            "/planning/participations/999999/respond/",
            body,
            content_type="application/json",
        )
        self.assertNotEqual(r1.status_code, 409)
        self.assertEqual(r2.status_code, 409)
        self.assertTrue(r2.json().get("duplicate"))