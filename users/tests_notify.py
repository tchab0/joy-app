from django.core import mail
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model

from users.notify import notify_users

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class NotifyFallbackTests(TestCase):
    def test_email_fallback_without_push(self):
        user = User.objects.create_user(
            username="notif1",
            email="notif1@example.com",
            password="x",
        )
        n = notify_users(
            [user],
            title="JOY — Test",
            body="Bonjour",
            url="/chat/",
        )
        self.assertEqual(n, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "JOY — Test")
        self.assertIn("Bonjour", mail.outbox[0].body)
        self.assertIn("/chat/", mail.outbox[0].body)

    def test_skip_without_email_or_push(self):
        user = User.objects.create_user(
            username="notif2",
            email="",
            password="x",
        )
        n = notify_users([user], title="JOY", body="x")
        self.assertEqual(n, 0)
        self.assertEqual(len(mail.outbox), 0)
