from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import ContactMessage

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SENDING_ENABLED=True,
)
class AdminContactActionsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="x",
            is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.staff)
        self.msg = ContactMessage.objects.create(
            kind=ContactMessage.KIND_CONTACT,
            nom="Ada Lovelace",
            email="ada@example.com",
            telephone="0600000000",
            message="Bonjour, dispo pour un bal ?",
        )

    def test_mark_spam(self):
        url = reverse("admin_contact_action", args=[self.msg.pk])
        resp = self.client.post(url, {"action": "spam"})
        self.assertEqual(resp.status_code, 302)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.statut, "spam")
        self.assertIsNotNone(self.msg.processed_at)

    def test_reply_sends_mail_and_marks_processed(self):
        url = reverse("admin_contact_action", args=[self.msg.pk])
        resp = self.client.post(
            url,
            {
                "action": "reply",
                "subject": "Re: Votre message",
                "body": "Bonjour Ada,\n\nOui avec plaisir.\n",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ada@example.com"])
        self.assertEqual(mail.outbox[0].subject, "Re: Votre message")
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.statut, "processed")

    def test_unspam_restores_new(self):
        self.msg.statut = "spam"
        self.msg.save(update_fields=["statut"])
        url = reverse("admin_contact_action", args=[self.msg.pk])
        resp = self.client.post(url, {"action": "unspam"})
        self.assertEqual(resp.status_code, 302)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.statut, "new")
