from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.mailing import (
    personalize,
    resolve_recipients,
    send_staff_mailing,
)
from core.models import StaffMailing

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StaffMailingServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="x",
            first_name="Alice",
            is_musician=True,
            is_active=True,
        )
        self.bob = User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password="x",
            first_name="",
            is_musician=True,
            is_active=True,
        )
        self.fake = User.objects.create_user(
            username="fake",
            email="fake@fake.net",
            password="x",
            first_name="Fake",
            is_musician=True,
            is_active=True,
        )
        self.staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="x",
            is_staff=True,
        )

    def test_personalize_musician_prenom(self):
        self.assertEqual(
            personalize("Bonjour {{prenom}},\n\nSuite.", "Alice"),
            "Bonjour Alice,\n\nSuite.",
        )

    def test_personalize_empty_becomes_bonjour_comma(self):
        self.assertEqual(
            personalize("Bonjour {{prenom}},\n\nSuite.", ""),
            "Bonjour,\n\nSuite.",
        )

    def test_resolve_skips_fake_by_default(self):
        recipients = resolve_recipients(
            musician_ids=[self.alice.pk, self.fake.pk],
            free_emails_raw="",
            include_fake=False,
        )
        emails = [r.email for r in recipients]
        self.assertEqual(emails, ["alice@example.com"])

    def test_resolve_free_emails_and_dedupe(self):
        recipients = resolve_recipients(
            musician_ids=[self.alice.pk],
            free_emails_raw="alice@example.com, other@example.com",
            include_fake=False,
        )
        emails = [r.email for r in recipients]
        self.assertEqual(emails, ["alice@example.com", "other@example.com"])
        free = [r for r in recipients if r.email == "other@example.com"][0]
        self.assertEqual(free.prenom, "")

    def test_username_fallback_for_prenom(self):
        recipients = resolve_recipients(
            musician_ids=[self.bob.pk],
            include_fake=False,
        )
        self.assertEqual(recipients[0].prenom, "bob")

    def test_send_personalizes_each_message(self):
        recipients = resolve_recipients(
            musician_ids=[self.alice.pk, self.bob.pk],
            free_emails_raw="guest@example.com",
        )
        mailing = send_staff_mailing(
            sent_by=self.staff,
            subject="Info {{prenom}}",
            body_template="Bonjour {{prenom}},\n\nRéunion lundi.",
            recipients=recipients,
        )
        self.assertEqual(mailing.sent_count, 3)
        self.assertEqual(mailing.failed_count, 0)
        self.assertEqual(len(mail.outbox), 3)

        by_to = {m.to[0]: m for m in mail.outbox}
        self.assertIn("Bonjour Alice,", by_to["alice@example.com"].body)
        self.assertEqual(by_to["alice@example.com"].subject, "Info Alice")
        self.assertIn("Bonjour bob,", by_to["bob@example.com"].body)
        self.assertIn("Bonjour,", by_to["guest@example.com"].body)
        self.assertEqual(by_to["guest@example.com"].subject, "Info")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StaffMailingViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.musician = User.objects.create_user(
            username="claire",
            email="claire@example.com",
            password="x",
            first_name="Claire",
            is_musician=True,
        )
        self.staff = User.objects.create_user(
            username="adminstaff",
            email="adminstaff@example.com",
            password="pass12345",
            is_staff=True,
        )
        self.url = reverse("admin_emails")

    def test_requires_staff(self):
        self.client.force_login(self.musician)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_preview_then_send(self):
        self.client.force_login(self.staff)
        preview = self.client.post(
            self.url,
            {
                "action": "preview",
                "subject": "Hello {{prenom}}",
                "body": "Bonjour {{prenom}},\n\nTest.",
                "musician_ids": [str(self.musician.pk)],
                "free_emails": "",
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Confirmer l’envoi")
        self.assertContains(preview, "Bonjour Claire,")

        send = self.client.post(
            self.url,
            {
                "action": "send",
                "subject": "Hello {{prenom}}",
                "body": "Bonjour {{prenom}},\n\nTest.",
                "musician_ids": [str(self.musician.pk)],
                "free_emails": "",
            },
        )
        self.assertEqual(send.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Bonjour Claire,", mail.outbox[0].body)
        self.assertEqual(StaffMailing.objects.count(), 1)
