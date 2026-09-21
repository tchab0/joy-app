from django.core import mail
from django.test import Client, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from users.models import UserNotification
from users.notify import mark_notifications_responded, notify_users, _relative_push_url

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

    def test_staff_alert_skipped_for_musician(self):
        musician = User.objects.create_user(
            username="musi_alert",
            email="musi_alert@example.com",
            password="x",
            is_staff=False,
        )
        staff = User.objects.create_user(
            username="staff_alert",
            email="staff_alert@example.com",
            password="x",
            is_staff=True,
        )
        n = notify_users(
            [musician, staff],
            title="JOY — Présence annulée",
            body="Un camarade ne vient plus.",
            url="/planning/",
            related_type="staff_alert",
            notify_type="staff_alert",
        )
        self.assertEqual(n, 1)
        self.assertEqual(
            UserNotification.objects.filter(user=musician).count(), 0
        )
        self.assertEqual(
            UserNotification.objects.filter(user=staff).count(), 1
        )

    def test_is_staff_destined_notification(self):
        from users.notify import is_staff_destined_notification

        staff_item = UserNotification(
            title="JOY — Présence annulée",
            body="x",
            related_type="staff_alert",
        )
        chat_staff = UserNotification(
            title="JOY — Staff",
            body="hello",
            related_type="chat_msg",
            url="/chat/1/",
        )
        chat_orch = UserNotification(
            title="JOY — Orchestre",
            body="hello",
            related_type="chat_msg",
            url="/chat/2/",
        )
        self.assertTrue(is_staff_destined_notification(staff_item))
        self.assertTrue(is_staff_destined_notification(chat_staff))
        self.assertFalse(is_staff_destined_notification(chat_orch))



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

    def test_musician_can_archive_and_hide_from_salon(self):
        notify_users(
            [self.musician], title="À ranger", body="Plus tard", url="/planning/"
        )
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.musician)

        r = self.client.post(
            reverse("account_notification_archive", args=[notif.pk]),
        )
        self.assertRedirects(r, reverse("account_notifications"))
        notif.refresh_from_db()
        self.assertIsNotNone(notif.archived_at)
        self.assertIsNotNone(notif.read_at)

        salon = self.client.get(reverse("account_notifications"))
        self.assertEqual(salon.status_code, 200)
        self.assertNotContains(salon, "À ranger")
        self.assertEqual(salon.context["unread_count"], 0)

        archives = self.client.get(
            reverse("account_notifications") + "?vue=archives"
        )
        self.assertEqual(archives.status_code, 200)
        self.assertContains(archives, "À ranger")
        self.assertTrue(archives.context["show_archives"])

        r2 = self.client.post(
            reverse("account_notification_unarchive", args=[notif.pk]),
            {"vue": "archives"},
        )
        self.assertRedirects(
            r2, reverse("account_notifications") + "?vue=archives"
        )
        notif.refresh_from_db()
        self.assertIsNone(notif.archived_at)
        self.assertIsNone(notif.read_at)
        salon2 = self.client.get(reverse("account_notifications"))
        self.assertContains(salon2, "À ranger")
        self.assertEqual(salon2.context["unread_count"], 1)

    def test_archive_json_and_excludes_from_unread_banner(self):
        notify_users(
            [self.musician],
            title="Swipe archive",
            body="body",
            url="/planning/",
        )
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.musician)
        r = self.client.post(
            reverse("account_notification_archive", args=[notif.pk]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        dash = self.client.get(reverse("planning:dashboard"))
        self.assertFalse(dash.context["show_coulisses_unread_banner"])
        self.assertEqual(dash.context["unread_inbox_count"], 0)

    def test_mark_read_json_hides_from_salon(self):
        notify_users(
            [self.musician], title="Info lue", body="ok", url="/planning/"
        )
        notif = UserNotification.objects.get(user=self.musician)
        self.client.force_login(self.musician)
        r = self.client.post(
            reverse("account_notification_mark_read", args=[notif.pk]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "mark_read")
        salon = self.client.get(reverse("account_notifications"))
        self.assertNotContains(salon, "Info lue")

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
        self.assertContains(r, "Merci de répondre")
        # Sous le menu Coulisses, pas au-dessus.
        self.assertLess(
            r.content.find(b'pl-nav__label">Planning'),
            r.content.find(b"Invite Coulisses"),
        )

    def test_coulisses_chat_unread_grouped_as_messages(self):
        notify_users(
            [self.musician],
            title="JOY — Salon orchestre",
            body="Alice vous a cité dans Salon orchestre : hello",
            url="/chat/1/?msg=10",
            related_type="chat_msg",
            related_id=10,
        )
        notify_users(
            [self.musician],
            title="JOY — Salon orchestre",
            body="Bob vous a cité dans Salon orchestre : world",
            url="/chat/1/?msg=11",
            related_type="chat_msg",
            related_id=11,
        )
        notify_users(
            [self.musician],
            title="JOY — Répétition",
            body="Alice vous a cité dans Répétition : ping",
            url="/chat/2/?msg=12",
            related_type="chat_msg",
            related_id=12,
        )
        self.client.force_login(self.musician)
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        banner = r.context["unread_inbox_banner"]
        self.assertEqual(banner["chat_total"], 3)
        self.assertEqual(len(banner["chat_groups"]), 2)
        self.assertContains(r, "Tout marquer lu")
        self.assertNotContains(r, ">Toutes</a>")
        self.assertContains(r, "2 messages non lus")
        self.assertContains(r, "Salon orchestre")
        self.assertContains(r, "Répétition")
        self.assertContains(r, "Alice vous a cité dans Répétition")
        self.assertNotContains(r, "Bob vous a cité dans Salon orchestre")
        self.assertNotContains(r, "Alice vous a cité dans Salon orchestre : hello")
        self.assertContains(r, reverse("chat:room", args=[1]))
        # Le groupe à une seule notif ouvre le salon (via le lien d’ouverture).
        solo = next(g for g in banner["chat_groups"] if g["count"] == 1)
        self.assertTrue(solo["show_content"])
        self.assertContains(
            r, reverse("account_notification_open", args=[solo["open_pk"]])
        )

    def test_coulisses_action_notifications_shown_before_chat(self):
        """Sondage / événement à répondre : listés avant le chat, avec point."""
        notify_users(
            [self.musician],
            title="JOY — Événement confirmé",
            body="Événement confirmé : « Concert » (01/10/2026 20:00).",
            url="/planning/1/",
            requires_response=True,
            related_type="event",
            related_id=1,
        )
        notify_users(
            [self.musician],
            title="JOY — Salon orchestre",
            body="Alice dans Orchestre : hello",
            url="/chat/1/",
            related_type="chat_msg",
            related_id=20,
        )
        self.client.force_login(self.musician)
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        banner = r.context["unread_inbox_banner"]
        self.assertEqual(len(banner["action"]), 1)
        self.assertEqual(banner["chat_total"], 1)
        self.assertContains(r, "pl-notif-banner__dot--action")
        self.assertContains(r, "Événement confirmé")
        self.assertNotContains(r, "pl-notif-banner__action-label")
        body = r.content.decode()
        self.assertLess(
            body.find("Événement confirmé"),
            body.find("Salon orchestre"),
        )

    def test_coulisses_chat_groups_expose_room_kind(self):
        from chat.models import ChatRoom
        from chat.services import (
            ensure_orchestra_room,
            ensure_rehearsals_room,
            ensure_staff_room,
        )
        from users.notify import (
            group_unread_inbox_for_banner,
            unread_notifications_for_user,
        )

        orch = ensure_orchestra_room()
        rehearse = ensure_rehearsals_room()
        private = ChatRoom.objects.create(
            kind=ChatRoom.Kind.EVENT, title="Privé · Alice"
        )
        piece = ChatRoom.objects.create(
            kind=ChatRoom.Kind.PIECE, title="Morceau · Take Five"
        )
        staff_room = ensure_staff_room()

        for room, body in (
            (orch, "msg orchestre"),
            (rehearse, "msg répé"),
            (private, "msg privé"),
            (piece, "msg morceau"),
            (staff_room, "msg staff"),
        ):
            notify_users(
                [self.musician],
                title=f"JOY — {room.title}",
                body=body,
                url=f"/chat/{room.pk}/",
                related_type="chat_msg",
                related_id=room.pk,
            )

        unread, _ = unread_notifications_for_user(self.musician)
        banner = group_unread_inbox_for_banner(unread)
        by_label = {g["label"]: g for g in banner["chat_groups"]}
        self.assertEqual(by_label[orch.title]["kind"], "orchestra")
        self.assertEqual(by_label[rehearse.title]["kind"], "rehearsals")
        self.assertEqual(by_label["Privé · Alice"]["kind"], "private")
        self.assertEqual(by_label["Morceau · Take Five"]["kind"], "piece")
        self.assertEqual(by_label[staff_room.title]["kind"], "staff")
        self.assertTrue(by_label[staff_room.title]["is_staff"])

        self.client.force_login(self.musician)
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pl-notif-banner__dot--chat-orchestra")
        self.assertContains(r, "pl-notif-banner__dot--chat-rehearsals")
        self.assertContains(r, "pl-notif-banner__dot--chat-private")
        self.assertContains(r, "pl-notif-banner__dot--chat-piece")
        self.assertContains(r, "pl-notif-banner__dot--chat-staff")

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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="test-pub",
    VAPID_PRIVATE_KEY="test-priv",
    SITE_URL="https://jazz-orchestra-yonnais.fr",
)
class PushNotificationUrlTests(TestCase):
    def test_relative_push_url_strips_site_origin(self):
        self.assertEqual(
            _relative_push_url("https://jazz-orchestra-yonnais.fr/chat/"),
            "/chat/",
        )
        self.assertEqual(_relative_push_url("/planning/"), "/planning/")

    def test_push_uses_open_endpoint(self):
        from unittest.mock import patch

        user = User.objects.create_user(
            username="push1",
            email="",
            password="x",
        )
        captured = {}

        def fake_push(sub, *, title, body, url):
            captured["url"] = url
            return True

        fake_sub = type("Sub", (), {"pk": 1, "user_agent": ""})()

        with patch("users.notify.vapid_configured", return_value=True), patch(
            "users.models.PushSubscription"
        ) as sub_cls, patch("users.notify.send_web_push", side_effect=fake_push):
            sub_cls.objects.filter.return_value = [fake_sub]
            notify_users([user], title="JOY", body="Salut", url="/chat/")

        notif = UserNotification.objects.get(user=user)
        self.assertEqual(
            captured["url"],
            reverse("account_notification_open", args=[notif.pk]),
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class NotificationOpenRedirectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="open1",
            email="open1@example.com",
            password="x",
        )
        self.client = Client()
        self.client.login(username="open1", password="x")

    def test_open_redirects_to_content_url(self):
        notif = UserNotification.objects.create(
            user=self.user,
            title="Salon",
            body="Nouveau message",
            url="/chat/42/?msg=99",
        )
        r = self.client.get(reverse("account_notification_open", args=[notif.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/chat/42/?msg=99")
        notif.refresh_from_db()
        self.assertIsNotNone(notif.read_at)

    def test_open_without_url_returns_inbox(self):
        notif = UserNotification.objects.create(
            user=self.user,
            title="Info",
            body="Sans lien",
            url="",
        )
        r = self.client.get(reverse("account_notification_open", args=[notif.pk]))
        self.assertRedirects(r, reverse("account_notifications"))
