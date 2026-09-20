from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model

from stats.services import resolve_period
from stats.tracking import feature_name_for_path, record_usage


class FeatureNameTests(SimpleTestCase):
    def test_planning_and_skips(self):
        self.assertEqual(feature_name_for_path("/planning/"), "planning.view")
        self.assertEqual(feature_name_for_path("/planning/moi/"), "planning.moi")
        self.assertEqual(feature_name_for_path("/chat/"), "chat.view")
        self.assertIsNone(feature_name_for_path("/stats/"))
        self.assertIsNone(feature_name_for_path("/repertoire/partition/12/"))
        self.assertIsNone(feature_name_for_path("/repertoire/morceau/foo/audio/"))
        self.assertEqual(feature_name_for_path("/repertoire/morceau/foo/"), "repertoire.view")


class PeriodTests(SimpleTestCase):
    def test_default_and_clamp(self):
        self.assertEqual(resolve_period(None).days, 30)
        self.assertEqual(resolve_period("7").days, 7)
        self.assertEqual(resolve_period("999").days, 30)


@override_settings(ALLOWED_HOSTS=["*"])
class UsageEventTests(TestCase):
    def test_record_usage(self):
        User = get_user_model()
        user = User.objects.create_user(username="statu", password="x")
        record_usage(name="planning.view", user=user, path="/planning/")
        from stats.models import UsageEvent

        self.assertEqual(UsageEvent.objects.count(), 1)
        self.assertEqual(UsageEvent.objects.get().name, "planning.view")


@override_settings(ALLOWED_HOSTS=["*"])
class DashboardRecentLoginsTests(TestCase):
    def test_recent_activity_prefers_last_seen_over_stale_login(self):
        from datetime import timedelta

        from django.utils import timezone

        from stats.services import build_dashboard_context, resolve_period

        User = get_user_model()
        now = timezone.now()
        stale_login = User.objects.create_user(
            username="stale_login", password="x", is_musician=True
        )
        stale_login.last_login = now - timedelta(days=10)
        stale_login.last_seen_at = now - timedelta(days=10)
        stale_login.save(update_fields=["last_login", "last_seen_at"])

        active_session = User.objects.create_user(
            username="active_session", password="x", is_musician=True
        )
        # Login formulaire vieux, mais visite session récente.
        active_session.last_login = now - timedelta(days=40)
        active_session.last_seen_at = now - timedelta(hours=1)
        active_session.save(update_fields=["last_login", "last_seen_at"])

        User.objects.create_user(
            username="never_seen", password="x", is_musician=True
        )

        ctx = build_dashboard_context(period=resolve_period("30"))
        recent = ctx["musicians"]["recent_logins"]
        self.assertEqual(
            [u.username for u in recent],
            ["active_session", "stale_login"],
        )
        self.assertEqual(ctx["musicians"]["login_buckets"]["7j"], 1)
        self.assertEqual(ctx["musicians"]["login_buckets"]["30j"], 2)
        self.assertEqual(ctx["musicians"]["login_buckets"]["never"], 1)

    def test_inactive_lists_never_seen_first(self):
        from datetime import timedelta

        from django.utils import timezone

        from stats.services import build_dashboard_context, resolve_period

        User = get_user_model()
        now = timezone.now()
        never = User.objects.create_user(
            username="never_inactive", password="x", is_musician=True
        )
        old = User.objects.create_user(
            username="old_inactive", password="x", is_musician=True
        )
        old.last_seen_at = now - timedelta(days=120)
        old.save(update_fields=["last_seen_at"])
        recent = User.objects.create_user(
            username="recent_active", password="x", is_musician=True
        )
        recent.last_seen_at = now - timedelta(days=2)
        recent.save(update_fields=["last_seen_at"])

        ctx = build_dashboard_context(period=resolve_period("30"))
        inactive = [u.username for u in ctx["musicians"]["inactive"]]
        self.assertEqual(inactive[:2], ["never_inactive", "old_inactive"])
        self.assertNotIn("recent_active", inactive)


@override_settings(ALLOWED_HOSTS=["*"])
class LastSeenTouchTests(TestCase):
    def test_authenticated_private_page_updates_last_seen(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="seen_u", password="x", is_musician=True
        )
        self.assertIsNone(user.last_seen_at)

        c = Client()
        self.assertTrue(c.login(username="seen_u", password="x"))
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)
        self.assertIsNotNone(user.last_seen_at)
        after_login = user.last_seen_at

        from datetime import timedelta

        from django.utils import timezone

        # Simule une activité session sans nouveau login formulaire.
        User.objects.filter(pk=user.pk).update(
            last_login=timezone.now() - timedelta(days=10),
            last_seen_at=timezone.now() - timedelta(days=2),
        )
        # Reset throttle session pour forcer un touch.
        session = c.session
        session.pop("_joy_last_seen_touch", None)
        session.save()

        r = c.get("/compte/", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
        self.assertEqual(r.status_code, 200)
        user.refresh_from_db()
        self.assertGreater(user.last_seen_at, after_login - timedelta(days=1))
        self.assertGreater(
            user.last_seen_at, timezone.now() - timedelta(minutes=5)
        )


@override_settings(ALLOWED_HOSTS=["*"])
class PublicPageViewTests(TestCase):
    def test_public_home_is_counted(self):
        from unittest import mock

        from django.core.cache import cache

        from stats.models import PublicPageView

        cache.clear()
        c = Client()
        with mock.patch("stats.tracking.secrets.randbelow", return_value=0):
            r = c.get("/", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.get("X-JOY-Page-Cache"), "HIT")
        self.assertGreaterEqual(PublicPageView.objects.filter(path="/").count(), 1)

    def test_bots_are_ignored(self):
        from stats.models import PublicPageView

        c = Client()
        c.get("/", HTTP_USER_AGENT="Googlebot/2.1")
        self.assertEqual(PublicPageView.objects.count(), 0)

    def test_private_paths_not_public_counted(self):
        from stats.models import PublicPageView

        c = Client()
        c.get("/compte/connexion/", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
        self.assertEqual(PublicPageView.objects.count(), 0)
