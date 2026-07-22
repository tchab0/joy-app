from django.test import SimpleTestCase, TestCase, override_settings
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
