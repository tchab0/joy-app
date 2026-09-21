from django.test import RequestFactory, TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile

from core.media_pending import invalidate_pending_media_count
from core.models import EvenementMedia, MediaItem
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


class MediasEventFilterTests(TestCase):
    def setUp(self):
        self.ev_a = EvenementMedia.objects.create(
            nom="Concert A", date=timezone.localdate() - timedelta(days=30)
        )
        self.ev_b = EvenementMedia.objects.create(
            nom="Concert B", date=timezone.localdate() - timedelta(days=10)
        )
        tiny = b"\xff\xd8\xff\xd9"  # minimal JPEG

        def photo(titre, evenement, **kwargs):
            data = {
                "type": "photo",
                "titre": titre,
                "publie": True,
                "statut": "publie",
                "evenement": evenement,
                "fichier": SimpleUploadedFile(
                    f"{titre}.jpg", tiny, content_type="image/jpeg"
                ),
            }
            data.update(kwargs)
            return MediaItem.objects.create(**data)

        photo("Photo A", self.ev_a)
        photo("Photo B1", self.ev_b)
        photo("Photo B2", self.ev_b)
        # Non publié → hors filtre / galerie.
        photo("Draft", self.ev_a, publie=False, statut="en_attente")

    def test_lists_all_event_groups_by_default(self):
        r = self.client.get(reverse("medias"), {"tri": "evenements"})
        self.assertEqual(r.status_code, 200)
        groupes = r.context["groupes_photos"]
        self.assertEqual([g["evenement"].pk for g in groupes], [self.ev_b.pk, self.ev_a.pk])
        self.assertIsNone(r.context["evenement_actif"])
        self.assertEqual(
            [ev.pk for ev in r.context["evenements_filtre"]],
            [self.ev_b.pk, self.ev_a.pk],
        )
        self.assertContains(r, 'id="media-evenement"')
        self.assertContains(r, "Tous les événements")

    def test_filters_photos_to_selected_event(self):
        r = self.client.get(
            reverse("medias"),
            {"tri": "evenements", "evenement": str(self.ev_a.pk)},
        )
        self.assertEqual(r.status_code, 200)
        groupes = r.context["groupes_photos"]
        self.assertEqual(len(groupes), 1)
        self.assertEqual(groupes[0]["evenement"], self.ev_a)
        self.assertEqual(len(groupes[0]["photos"]), 1)
        self.assertEqual(r.context["evenement_actif"], self.ev_a)
        self.assertContains(r, f'value="{self.ev_a.pk}" selected')
        self.assertEqual([g["evenement"].nom for g in groupes], ["Concert A"])

    def test_invalid_event_id_shows_all(self):
        r = self.client.get(
            reverse("medias"),
            {"tri": "evenements", "evenement": "999999"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["evenement_actif"])
        self.assertEqual(len(r.context["groupes_photos"]), 2)

    def test_votes_tab_hides_event_filter(self):
        r = self.client.get(reverse("medias"), {"tri": "votes"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["evenement_actif"])
        self.assertEqual(len(r.context["photos_votes"]), 3)
        self.assertNotContains(r, 'id="media-evenement"')
