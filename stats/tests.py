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
    def test_recent_logins_ordered(self):
        from datetime import timedelta

        from django.utils import timezone

        from stats.services import build_dashboard_context, resolve_period

        User = get_user_model()
        now = timezone.now()
        older = User.objects.create_user(
            username="old_login", password="x", is_musician=True
        )
        older.last_login = now - timedelta(days=5)
        older.save(update_fields=["last_login"])
        newer = User.objects.create_user(
            username="new_login", password="x", is_musician=True
        )
        newer.last_login = now - timedelta(hours=1)
        newer.save(update_fields=["last_login"])
        User.objects.create_user(
            username="never_login", password="x", is_musician=True
        )

        ctx = build_dashboard_context(period=resolve_period("30"))
        recent = ctx["musicians"]["recent_logins"]
        self.assertEqual([u.username for u in recent], ["new_login", "old_login"])


@override_settings(ALLOWED_HOSTS=["*"])
class PublicPageViewTests(TestCase):
    def test_public_home_is_counted(self):
        from stats.models import PublicPageView

        c = Client()
        r = c.get("/", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
        self.assertEqual(r.status_code, 200)
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
