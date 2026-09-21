from django.test import RequestFactory, TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse

from core.media_pending import invalidate_pending_media_count
from core.models import MediaItem
from core.views import _notifier_admin
from users.models import User, UserNotification


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SENDING_ENABLED=True,
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class PendingMediaStaffTests(TestCase):
    def setUp(self):
        invalidate_pending_media_count()
        self.staff_a = User.objects.create_user(
            "staff_media_a", "staff-media-a@example.com", "x", is_staff=True
        )
        self.staff_b = User.objects.create_user(
            "staff_media_b", "staff-media-b@example.com", "x", is_staff=True
        )
        self.musician = User.objects.create_user(
            "mus_media", "mus-media@example.com", "x", is_staff=False
        )

    def _media(self, **kwargs):
        data = {"type": "photo", "titre": "Concert", "statut": "en_attente", "soumis_par_nom": "Ada"}
        data.update(kwargs)
        return MediaItem.objects.create(**data)

    def test_notifier_reaches_every_active_staff(self):
        media = self._media()
        _notifier_admin(media, nb=2)
        for user in (self.staff_a, self.staff_b):
            notif = UserNotification.objects.get(user=user, related_type="media")
            self.assertEqual(notif.url, "/admin-medias/")
            self.assertIn("2", notif.title)
        self.assertFalse(UserNotification.objects.filter(user=self.musician).exists())

    def test_submitting_staff_is_not_notified(self):
        _notifier_admin(self._media(), exclude_user=self.staff_a)
        self.assertFalse(UserNotification.objects.filter(user=self.staff_a).exists())
        self.assertTrue(UserNotification.objects.filter(user=self.staff_b).exists())

    def test_staff_menus_show_dot_until_media_is_treated(self):
        self.client.force_login(self.staff_a)
        before = self.client.get(reverse("admin_hub"))
        self.assertNotContains(before, 'aria-label="Médias,')

        media = self._media()
        invalidate_pending_media_count()
        pending = self.client.get(reverse("admin_hub"))
        self.assertContains(pending, 'aria-label="Médias, 1 à traiter"')
        self.assertContains(pending, 'class="staff-pending-dot"')

        request = RequestFactory().get("/")
        request.user = self.staff_a
        nav = render_to_string(
            "planning/_module_nav.html",
            {
                "pending_media_count": 1,
                "is_planning_staff": True,
                "active": "",
            },
            request=request,
        )
        self.assertIn('aria-label="Médias, 1 à traiter"', nav)
        self.assertIn('class="staff-pending-dot"', nav)
        self.assertIn(reverse("admin_medias"), nav)

        self.client.post(
            reverse("admin_media_action", args=[media.pk]),
            {"action": "publier"},
        )
        done = self.client.get(reverse("admin_hub"))
        self.assertNotContains(done, 'aria-label="Médias,')
