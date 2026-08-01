from django.core import mail
from django.test import Client, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from users.models import UserNotification
from users.notify import mark_notifications_responded, notify_users

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
        inbox = UserNotification.objects.filter(user=user)
        self.assertEqual(inbox.count(), 1)
        self.assertEqual(inbox[0].title, "JOY — Test")
        self.assertEqual(inbox[0].url, "/chat/")
        self.assertIsNone(inbox[0].read_at)
        self.assertFalse(inbox[0].requires_response)

    def test_skip_without_email_or_push(self):
        user = User.objects.create_user(
            username="notif2",
            email="",
            password="x",
        )
        n = notify_users([user], title="JOY", body="x")
        self.assertEqual(n, 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(UserNotification.objects.filter(user=user).count(), 1)

    def test_requires_response_persisted(self):
        user = User.objects.create_user(
            username="notif3",
            email="n3@example.com",
            password="x",
        )
        notify_users(
            [user],
            title="Invite",
            body="Réponds",
            url="/planning/",
            requires_response=True,
            related_type="event",
            related_id=42,
        )
        n = UserNotification.objects.get(user=user)
        self.assertTrue(n.requires_response)
        self.assertTrue(n.is_unanswered)
        self.assertEqual(n.related_type, "event")
        self.assertEqual(n.related_id, 42)
        mark_notifications_responded(user, related_type="event", related_id=42)
        n.refresh_from_db()
        self.assertFalse(n.is_unanswered)
        self.assertIsNotNone(n.responded_at)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class StaffUnreadNotificationsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staff1",
            email="staff@example.com",
            password="x",
            is_staff=True,
        )
        self.musician = User.objects.create_user(
            username="musi1",
            email="musi@example.com",
            password="x",
            is_musician=True,
        )
        self.other = User.objects.create_user(
            username="other1",
            email="other@example.com",
            password="x",
            is_musician=False,
        )
        self.client = Client()

    def test_staff_lists_pending_unread_and_unanswered(self):
        notify_users(
            [self.musician],
            title="Invite",
            body="Concert samedi",
            url="/planning/",
            requires_response=True,
            related_type="event",
            related_id=1,
        )
        info = UserNotification.objects.create(
            user=self.musician,
            title="Info lue non action",
            body="ok",
            url="/",
        )
        info.mark_read()
        notify_users(
            [self.other],
            title="Contact",
            body="Nouveau message",
            url="/admin-contact/",
        )

        self.client.force_login(self.staff)
        r = self.client.get(reverse("admin_notifications"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["filtre_actif"], "en-attente")
        self.assertContains(r, "Invite")
        self.assertContains(r, "Non lue")
        self.assertContains(r, "Non répondue")
        self.assertNotContains(r, "Info lue non action")
        self.assertNotContains(r, "Nouveau message")

        r2 = self.client.get(
            reverse("admin_notifications") + "?filtre=non-repondues"
        )
        self.assertContains(r2, "Invite")
        self.assertEqual(r2.context["count_unanswered"], 1)

        # Lire sans répondre → reste en non-répondues
        notif = UserNotification.objects.get(title="Invite")
        notif.mark_read()
        r3 = self.client.get(
            reverse("admin_notifications") + "?filtre=non-repondues"
        )
        self.assertContains(r3, "Invite")
        r4 = self.client.get(
            reverse("admin_notifications") + "?filtre=non-lues"
        )
        self.assertNotContains(r4, "Invite")

    def test_staff_can_delete(self):
        notify_users([self.musician], title="À supprimer", body="body", url="/")
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.staff)
        r = self.client.post(
            reverse("admin_notification_delete", args=[notif.pk]),
        )
        self.assertRedirects(r, reverse("admin_notifications"))
        self.assertFalse(UserNotification.objects.filter(pk=notif.pk).exists())

    def test_musician_can_mark_read(self):
        notify_users([self.musician], title="RSVP", body="Réponds", url="/planning/")
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.musician)
        r = self.client.post(
            reverse("account_notification_mark_read", args=[notif.pk]),
        )
        self.assertRedirects(r, reverse("account_notifications"))
        notif.refresh_from_db()
        self.assertIsNotNone(notif.read_at)

    def test_coulisses_planning_shows_unread_before_calendar(self):
        notify_users(
            [self.musician],
            title="Invite Coulisses",
            body="Merci de répondre",
            url="/planning/",
        )
        self.client.force_login(self.musician)
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["show_coulisses_unread_banner"])
        self.assertEqual(r.context["unread_inbox_count"], 1)
        self.assertContains(r, "Invite Coulisses")
        self.assertContains(r, "notification non lue")
        # Bannière avant le titre Planning du calendrier.
        self.assertLess(
            r.content.find(b"Invite Coulisses"),
            r.content.find(b"<h1>Planning</h1>"),
        )

    def test_coulisses_chat_unread_grouped_as_messages(self):
        notify_users(
            [self.musician],
            title="JOY — Salon orchestre",
            body="Alice vous a cité : hello",
            url="/chat/1/",
            related_type="chat_msg",
            related_id=10,
        )
        notify_users(
            [self.musician],
            title="JOY — Salon orchestre",
            body="Bob vous a cité : world",
            url="/chat/1/",
            related_type="chat_msg",
            related_id=11,
        )
        notify_users(
            [self.musician],
            title="JOY — Répétition",
            body="Alice vous a cité : ping",
            url="/chat/2/",
            related_type="chat_msg",
            related_id=12,
        )
        self.client.force_login(self.musician)
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        banner = r.context["unread_inbox_banner"]
        self.assertEqual(banner["chat_total"], 3)
        self.assertEqual(len(banner["chat_groups"]), 2)
        self.assertContains(r, "messages non lus")
        self.assertContains(r, "Salon orchestre")
        self.assertContains(r, "Répétition")
        self.assertContains(r, "Bob vous a cité")
        self.assertNotContains(r, "Alice vous a cité : hello")

    def test_home_hides_coulisses_unread_banner(self):
        notify_users(
            [self.musician],
            title="Hors Coulisses",
            body="Ne pas afficher sur l’accueil",
            url="/planning/",
        )
        self.client.force_login(self.musician)
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["show_coulisses_unread_banner"])
        self.assertNotContains(r, "Hors Coulisses")

    def test_mark_read_honors_next_back_to_planning(self):
        notify_users([self.musician], title="RSVP", body="Réponds", url="/planning/")
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.musician)
        r = self.client.post(
            reverse("account_notification_mark_read", args=[notif.pk]),
            {"next": reverse("planning:dashboard")},
        )
        self.assertRedirects(r, reverse("planning:dashboard"))
        notif.refresh_from_db()
        self.assertIsNotNone(notif.read_at)
