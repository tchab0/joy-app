from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from chat.models import ChatMembership
from chat.services import ensure_orchestra_room, post_message, sync_musician_to_orchestra
from users.digest import send_due_notification_digests
from users.models import NotificationTypePref, UserNotification
from users.notify import notify_users
from users.notify_prefs import (
    FREQ_DAILY,
    FREQ_EVERY_2_DAYS,
    FREQ_REALTIME,
    FREQ_WEEKLY,
    TYPE_EVENT,
    digest_is_due,
    resolve_delivery,
)

User = get_user_model()
PARIS = ZoneInfo("Europe/Paris")


class DigestScheduleTests(TestCase):
    def test_daily_due_after_hour(self):
        last = datetime(2026, 9, 7, 18, 5, tzinfo=PARIS)
        now = datetime(2026, 9, 8, 18, 10, tzinfo=PARIS)
        self.assertTrue(digest_is_due(FREQ_DAILY, 18, None, last, now))
        morning = datetime(2026, 9, 8, 10, 0, tzinfo=PARIS)
        self.assertFalse(digest_is_due(FREQ_DAILY, 18, None, last, morning))

    def test_daily_first_send_waits_for_hour(self):
        now = datetime(2026, 9, 8, 10, 0, tzinfo=PARIS)
        self.assertFalse(digest_is_due(FREQ_DAILY, 18, None, None, now))
        evening = datetime(2026, 9, 8, 18, 1, tzinfo=PARIS)
        self.assertTrue(digest_is_due(FREQ_DAILY, 18, None, None, evening))

    def test_every_2_days(self):
        last = datetime(2026, 9, 7, 18, 5, tzinfo=PARIS)  # Monday
        tue = datetime(2026, 9, 8, 18, 10, tzinfo=PARIS)
        wed = datetime(2026, 9, 9, 18, 10, tzinfo=PARIS)
        self.assertFalse(digest_is_due(FREQ_EVERY_2_DAYS, 18, None, last, tue))
        self.assertTrue(digest_is_due(FREQ_EVERY_2_DAYS, 18, None, last, wed))

    def test_weekly(self):
        # Wednesday = 2
        last = datetime(2026, 9, 2, 18, 5, tzinfo=PARIS)  # previous Wednesday
        this_wed = datetime(2026, 9, 9, 18, 10, tzinfo=PARIS)
        this_tue = datetime(2026, 9, 8, 18, 10, tzinfo=PARIS)
        self.assertTrue(digest_is_due(FREQ_WEEKLY, 18, 2, last, this_wed))
        self.assertFalse(digest_is_due(FREQ_WEEKLY, 18, 2, last, this_tue))

    def test_realtime_always_due(self):
        self.assertTrue(digest_is_due(FREQ_REALTIME, 18, None, None, timezone.now()))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class NotifyFrequencyDeliveryTests(TestCase):
    def test_daily_creates_inbox_without_email(self):
        user = User.objects.create_user(
            username="daily1",
            email="daily1@example.com",
            password="x",
            notify_frequency=FREQ_DAILY,
            notify_digest_hour=18,
        )
        n = notify_users(
            [user],
            title="JOY — Invitation",
            body="Concert",
            url="/planning/",
            related_type="event",
            related_id=1,
            notify_type="event",
        )
        self.assertEqual(n, 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(UserNotification.objects.filter(user=user).count(), 1)

    def test_realtime_sends_email(self):
        user = User.objects.create_user(
            username="rt1",
            email="rt1@example.com",
            password="x",
            notify_frequency=FREQ_REALTIME,
        )
        n = notify_users(
            [user],
            title="JOY — Invitation",
            body="Concert",
            url="/planning/",
            related_type="event",
            related_id=1,
        )
        self.assertEqual(n, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_type_override_realtime_while_default_daily(self):
        user = User.objects.create_user(
            username="ov1",
            email="ov1@example.com",
            password="x",
            notify_frequency=FREQ_DAILY,
            notify_digest_hour=18,
        )
        NotificationTypePref.objects.create(
            user=user,
            notify_type=TYPE_EVENT,
            frequency=FREQ_REALTIME,
        )
        n = notify_users(
            [user],
            title="Invite",
            body="Go",
            url="/planning/",
            related_type="event",
            notify_type="event",
        )
        self.assertEqual(n, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_mentions_force_immediate_despite_daily(self):
        user = User.objects.create_user(
            username="men1",
            email="men1@example.com",
            password="x",
            notify_frequency=FREQ_DAILY,
            notify_digest_hour=18,
        )
        n = notify_users(
            [user],
            title="JOY — Salon",
            body="Mention",
            url="/chat/1/",
            related_type="chat_msg",
            notify_type="chat",
            force_immediate=True,
        )
        self.assertEqual(n, 1)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class DigestCommandFrequencyTests(TestCase):
    def setUp(self):
        self.musician = User.objects.create_user(
            username="dig_musi",
            email="dig@example.com",
            password="pass",
            is_musician=True,
            notify_frequency=FREQ_DAILY,
            notify_digest_hour=18,
        )
        self.other = User.objects.create_user(
            username="dig_other",
            email="other@example.com",
            password="pass",
            is_musician=True,
            notify_frequency=FREQ_REALTIME,
        )

    def test_daily_chat_waits_until_hour(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        other_m = sync_musician_to_orchestra(self.other)
        other_m.subscribed = False
        other_m.save(update_fields=["subscribed"])
        post_message(room=room, author=self.other, body="Ping digest daily")

        morning = datetime(2026, 9, 8, 10, 0, tzinfo=PARIS)
        sent = send_due_notification_digests(now=morning, dry_run=False)
        self.assertEqual(sent, 0)
        self.assertEqual(len(mail.outbox), 0)
        m = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertEqual(m.last_digested_message_id, 0)

        evening = datetime(2026, 9, 8, 18, 15, tzinfo=PARIS)
        sent = send_due_notification_digests(now=evening, dry_run=False)
        self.assertGreaterEqual(sent, 1)
        self.assertGreater(len(mail.outbox), 0)
        m.refresh_from_db()
        self.assertGreater(m.last_digested_message_id, 0)

    def test_inbox_digest_for_daily_user(self):
        notify_users(
            [self.musician],
            title="JOY — Invitation",
            body="Concert samedi",
            url="/planning/",
            related_type="event",
            related_id=9,
            notify_type="event",
        )
        self.assertEqual(len(mail.outbox), 0)
        evening = datetime(2026, 9, 8, 18, 20, tzinfo=PARIS)
        sent = send_due_notification_digests(now=evening, dry_run=False)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.musician.refresh_from_db()
        self.assertIsNotNone(self.musician.notify_digest_last_sent_at)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class NotifyPrefsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="prefs_musi",
            email="prefs@example.com",
            password="pass",
            is_musician=True,
        )
        self.client = Client()
        self.client.login(username="prefs_musi", password="pass")

    def test_prefs_get_and_post(self):
        r = self.client.get(reverse("chat:prefs"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fréquence par défaut")
        r = self.client.post(
            reverse("chat:prefs"),
            {
                "notify_frequency": FREQ_EVERY_2_DAYS,
                "notify_digest_hour": 9,
                "notify_digest_weekday": 0,
                "chat_auto_subscribe": True,
                "ov_type_event": FREQ_REALTIME,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.notify_frequency, FREQ_EVERY_2_DAYS)
        self.assertEqual(self.user.notify_digest_hour, 9)
        pref = NotificationTypePref.objects.get(user=self.user, notify_type=TYPE_EVENT)
        self.assertEqual(pref.frequency, FREQ_REALTIME)

    def test_room_override_saved(self):
        room = ensure_orchestra_room()
        m = sync_musician_to_orchestra(self.user)
        r = self.client.post(
            reverse("chat:prefs"),
            {
                "notify_frequency": FREQ_REALTIME,
                "notify_digest_hour": 18,
                "notify_digest_weekday": 0,
                "chat_auto_subscribe": True,
                f"ov_room_{m.pk}": FREQ_DAILY,
                f"ov_room_{m.pk}_hour": 7,
            },
        )
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.notify_frequency_override, FREQ_DAILY)
        self.assertEqual(m.notify_digest_hour, 7)
        policy = resolve_delivery(self.user, "chat", room=room, membership=m)
        self.assertEqual(policy.frequency, FREQ_DAILY)
        self.assertEqual(policy.hour, 7)
        self.assertEqual(policy.source, "room")
