from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from feedback.models import PageFeedback, PageFeedbackMessage
from feedback.services.page_feedback import create_page_feedback
from users.models import UserNotification

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class NewFeedbackNotifyTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="auteur-notif",
            email="auteur-notif@example.com",
            password="x",
            first_name="Léa",
            last_name="Martin",
            is_musician=True,
        )
        self.admin = User.objects.create_user(
            username="thierry",
            email="thierry@example.com",
            password="x",
            first_name="Thierry",
            last_name="Chabot",
            is_staff=True,
            is_superuser=True,
        )

    def test_create_page_feedback_notifies_staff(self):
        feedback = create_page_feedback(
            author=self.author,
            category=PageFeedback.CATEGORY_BUG,
            message="Le bouton Envoyer ne répond pas sur mobile.",
            page_url="/planning/",
            page_title="Planning",
        )
        inbox = UserNotification.objects.filter(user=self.admin, related_type="feedback")
        self.assertEqual(inbox.count(), 1)
        notif = inbox.get()
        self.assertEqual(notif.title, "JOY — Nouveau retour")
        self.assertIn("Martin Léa", notif.body)
        self.assertIn(f"feedback_focus={feedback.pk}", notif.url)
        self.assertFalse(
            UserNotification.objects.filter(user=self.author, related_type="feedback").exists()
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class FeedbackThreadTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            username="auteur",
            email="auteur@example.com",
            password="x",
            first_name="Léa",
            last_name="Martin",
            is_musician=True,
        )
        self.admin = User.objects.create_user(
            username="adminjoy",
            email="admin@example.com",
            password="x",
            first_name="Admin",
            last_name="JOY",
            is_staff=True,
        )
        self.other = User.objects.create_user(
            username="autre",
            email="autre@example.com",
            password="x",
            is_musician=True,
        )
        self.feedback = PageFeedback.objects.create(
            author=self.author,
            category=PageFeedback.CATEGORY_BUG,
            message="Le bouton Envoyer ne répond pas sur mobile.",
            page_url="/planning/",
            page_title="Planning",
        )

    def _post_message(self, user, body, *, feedback_id=None):
        self.client.force_login(user)
        return self.client.post(
            reverse("post_page_feedback_message", args=[feedback_id or self.feedback.pk]),
            {"body": body, "feedback_view": "pending"},
        )

    def test_admin_and_author_can_exchange_messages(self):
        r = self._post_message(self.admin, "Peux-tu préciser sur quel navigateur ?")
        self.assertEqual(r.status_code, 302)
        msg = PageFeedbackMessage.objects.get(feedback=self.feedback)
        self.assertTrue(msg.is_from_staff)
        self.assertEqual(msg.sender, self.admin)

        inbox = UserNotification.objects.filter(user=self.author, related_type="feedback")
        self.assertEqual(inbox.count(), 1)
        self.assertIn(f"#retour-{self.feedback.pk}", inbox.get().url)

        r = self._post_message(self.author, "Sur Firefox Android, le bouton ne fait rien.")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PageFeedbackMessage.objects.filter(feedback=self.feedback).count(), 2)
        reply = PageFeedbackMessage.objects.filter(is_from_staff=False).get()
        self.assertEqual(reply.sender, self.author)

        staff_inbox = UserNotification.objects.filter(user=self.admin, related_type="feedback")
        self.assertEqual(staff_inbox.count(), 1)
        self.assertIn("feedback_focus=", staff_inbox.get().url)

    def test_message_on_treated_feedback_notifies_recipient(self):
        from django.core import mail
        from django.utils import timezone

        self.feedback.treated_at = timezone.now()
        self.feedback.treated_by = self.admin
        self.feedback.save(update_fields=["treated_at", "treated_by"])
        self.author.notify_frequency = User.NotifyFrequency.DAILY
        self.author.save(update_fields=["notify_frequency"])

        r = self._post_message(self.admin, "C'est en ligne, tu peux retester.")
        self.assertEqual(r.status_code, 302)
        author_inbox = UserNotification.objects.filter(
            user=self.author, related_type="feedback"
        )
        self.assertEqual(author_inbox.count(), 1)
        self.assertIn(f"#retour-{self.feedback.pk}", author_inbox.get().url)
        self.assertTrue(any("retester" in m.body for m in mail.outbox))

        mail.outbox.clear()
        r = self._post_message(
            self.author, "Merci, je confirme que c'est bon maintenant."
        )
        self.assertEqual(r.status_code, 302)
        staff_inbox = UserNotification.objects.filter(
            user=self.admin, related_type="feedback"
        )
        self.assertEqual(staff_inbox.count(), 1)
        self.assertIn("feedback_view=treated", staff_inbox.get().url)
        self.assertIn(f"feedback_focus={self.feedback.pk}", staff_inbox.get().url)

    def test_stranger_cannot_write(self):
        r = self._post_message(self.other, "Je me greffe sur ce retour.")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PageFeedbackMessage.objects.exists())

    def test_empty_message_rejected(self):
        r = self._post_message(self.admin, "   ")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PageFeedbackMessage.objects.exists())

    def test_account_lists_thread_for_author(self):
        PageFeedbackMessage.objects.create(
            feedback=self.feedback,
            sender=self.admin,
            body="On regarde ça.",
            is_from_staff=True,
        )
        self.client.force_login(self.author)
        r = self.client.get(reverse("account_home"))
        self.assertContains(r, "On regarde ça.")
        self.assertContains(r, f'id="retour-{self.feedback.pk}"')
        self.assertContains(r, "Ajouter une précision ou répondre au staff")

    def test_admin_page_shows_thread_form(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("admin_feedback"))
        self.assertContains(r, "Demander un détail, préciser une correction")
        self.assertContains(r, reverse("post_page_feedback_message", args=[self.feedback.pk]))
