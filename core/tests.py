from pathlib import Path
from datetime import timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from core.media_pending import invalidate_pending_media_count
from core.models import EvenementMedia, MediaItem
from core.views import (
    _compress_then_notify_staff,
    _notifier_admin,
)
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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SENDING_ENABLED=True,
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
class VideoCompressionNotifyTests(TestCase):
    """Alerte staff « à valider » seulement après compression + fichier accessible."""

    def setUp(self):
        import tempfile

        invalidate_pending_media_count()
        self._tmp = tempfile.TemporaryDirectory()
        self._media_override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(self._tmp.cleanup)

        self.staff = User.objects.create_user(
            "staff_vid", "staff-vid@example.com", "x", is_staff=True
        )
        self.submitter = User.objects.create_user(
            "staff_submit", "staff-submit@example.com", "x", is_staff=True
        )

    def _video_with_source(self, **kwargs):
        from django.conf import settings

        data = {
            "type": "video",
            "titre": "Concert CYEL",
            "statut": "en_attente",
            "publie": False,
            "soumis_par_nom": "Thierry Bussy",
        }
        data.update(kwargs)
        media = MediaItem.objects.create(**data)
        rel = f"medias/2026/09/clip-{media.pk}.mp4"
        src = Path(settings.MEDIA_ROOT) / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake-video-bytes")
        media.fichier.name = rel
        media.save(update_fields=["fichier"])
        return media

    def _notify_titles(self):
        return list(
            UserNotification.objects.filter(related_type="media").values_list(
                "title", flat=True
            )
        )

    def test_no_validate_notify_while_compression_in_progress(self):
        from unittest.mock import patch

        media = self._video_with_source()

        def fake_compress(item):
            item.statut = "en_cours"
            item.save(update_fields=["statut"])
            self.assertFalse(
                UserNotification.objects.filter(related_type="media").exists(),
                "Aucune alerte pendant en_cours",
            )
            return "ok"

        with patch("core.views.compresser_media", side_effect=fake_compress):
            _compress_then_notify_staff(media.pk, exclude_user_id=self.submitter.pk)

        # fake_compress laisse en_cours → pas d’alerte « à valider »
        self.assertEqual(self._notify_titles(), [])

    def test_validate_notify_after_accessible_compressed_file(self):
        from unittest.mock import patch

        media = self._video_with_source()

        def fake_compress(item):
            dest = item.compressed_sidecar_dest()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"compressed-mp4")
            item.statut = "en_attente"
            item.save(update_fields=["statut"])
            self.assertFalse(
                UserNotification.objects.filter(related_type="media").exists(),
                "Pas de notif avant la fin de compression",
            )
            return "ok"

        with patch("core.views.compresser_media", side_effect=fake_compress):
            _compress_then_notify_staff(media.pk, exclude_user_id=self.submitter.pk)

        media.refresh_from_db()
        self.assertEqual(media.statut, "en_attente")
        compressed = media.chemin_compresse()
        self.assertIsNotNone(compressed)
        self.assertTrue(compressed.exists())
        titles = self._notify_titles()
        self.assertEqual(len(titles), 1)  # staff only (submitter excluded)
        self.assertIn("à valider", titles[0])
        notif = UserNotification.objects.get(user=self.staff, related_type="media")
        self.assertEqual(notif.url, "/admin-medias/")
        self.assertFalse(
            UserNotification.objects.filter(user=self.submitter, related_type="media").exists()
        )

    def test_no_validate_notify_on_compression_failure(self):
        from unittest.mock import patch

        media = self._video_with_source()

        def fake_compress(item):
            item.statut = "en_attente"
            item.note_admin = "Erreur compression : ffmpeg boom"
            item.save(update_fields=["statut", "note_admin"])
            return "error"

        with patch("core.views.compresser_media", side_effect=fake_compress):
            _compress_then_notify_staff(media.pk, exclude_user_id=self.submitter.pk)

        titles = self._notify_titles()
        self.assertEqual(len(titles), 1)
        self.assertIn("Compression média échouée", titles[0])
        self.assertNotIn("à valider", titles[0])

    def test_no_notify_when_recompressing_published_video(self):
        from unittest.mock import patch

        media = self._video_with_source(statut="publie", publie=True)

        def fake_compress(item):
            # Comme compresser_media réel : ne pas rebasculer un publié.
            item.statut = "publie"
            item.save(update_fields=["statut"])
            return "ok"

        with patch("core.views.compresser_media", side_effect=fake_compress):
            _compress_then_notify_staff(media.pk)

        self.assertEqual(self._notify_titles(), [])


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


class CompressedSidecarUniquenessTests(TestCase):
    """Deux photos éditées « photo-editee.jpg » ne doivent pas partager le WebP."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._media_override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(self._tmp.cleanup)

    def _jpeg(self, color):
        from io import BytesIO
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (80, 60), color).save(buf, "JPEG")
        return buf.getvalue()

    def _place_edit(self, media, rel, color):
        from django.conf import settings

        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._jpeg(color))
        media.fichier_edite.name = rel
        media.save(update_fields=["fichier_edite"])
        return media

    def test_same_edit_stem_gets_distinct_display_urls(self):
        from core.utils_compression import compresser_media

        ev_a = EvenementMedia.objects.create(nom="Marché", date=timezone.localdate())
        ev_b = EvenementMedia.objects.create(nom="Groove Circle", date=timezone.localdate())
        a = MediaItem.objects.create(
            type="photo", titre="Marché", publie=True, statut="publie", evenement=ev_a
        )
        b = MediaItem.objects.create(
            type="photo", titre="Groove Circle", publie=True, statut="publie", evenement=ev_b
        )
        self._place_edit(a, "medias/edites/2026/07/photo-editee.jpg", (200, 40, 40))
        self._place_edit(b, "medias/edites/2026/09/photo-editee.jpg", (20, 40, 200))

        compresser_media(a)
        compresser_media(b)
        a.refresh_from_db()
        b.refresh_from_db()

        self.assertTrue(a.url_affichage)
        self.assertTrue(b.url_affichage)
        self.assertNotEqual(a.url_affichage, b.url_affichage)
        self.assertIn(f"{a.pk}_photo-editee", a.url_affichage)
        self.assertIn(f"{b.pk}_photo-editee", b.url_affichage)

        dest_a = a.chemin_compresse()
        dest_b = b.chemin_compresse()
        self.assertIsNotNone(dest_a)
        self.assertIsNotNone(dest_b)
        self.assertNotEqual(dest_a.read_bytes(), dest_b.read_bytes())

    def test_legacy_sidecar_still_found_if_unique_missing(self):
        from django.conf import settings
        from PIL import Image

        media = MediaItem.objects.create(
            type="photo", titre="Ancien", publie=True, statut="publie"
        )
        media.fichier.name = "medias/2026/01/legacy-stem.jpg"
        media.save(update_fields=["fichier"])
        dest = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
        dest.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), (8, 8, 8)).save(dest / "legacy-stem.webp", "WEBP")
        self.assertTrue(str(media.chemin_compresse()).endswith("legacy-stem.webp"))
        self.assertIn("legacy-stem.webp", media.url_affichage)

    def test_video_compression_uses_h264_not_hevc(self):
        """H.264 web-compatible — HEVC often plays as audio-only in Chrome/Firefox."""
        from unittest.mock import patch

        from django.conf import settings

        from core.utils_compression import compresser_media

        media = MediaItem.objects.create(
            type="video", titre="Clip", publie=True, statut="publie"
        )
        rel = "medias/2026/09/clip-src.mp4"
        src = Path(settings.MEDIA_ROOT) / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake-video")
        media.fichier.name = rel
        media.save(update_fields=["fichier"])

        with patch("core.utils_compression.subprocess.run") as run:
            compresser_media(media)
            run.assert_called_once()
            cmd = run.call_args.args[0]
        self.assertIn("libx264", cmd)
        self.assertNotIn("libx265", cmd)
        self.assertIn("yuv420p", cmd)
        dest = media.compressed_sidecar_dest()
        self.assertIsNotNone(dest)
        self.assertEqual(dest.name, f"{media.pk}_clip-src.mp4")
        self.assertEqual(cmd[-1], str(dest))


class AdminMediaAttachChoicesTests(TestCase):
    """Le menu « rattacher » ne propose que les événements galerie, une fois chacun."""

    def setUp(self):
        self.staff = User.objects.create_user(
            "staff_rattach", "staff-rattach@example.com", "x", is_staff=True
        )
        today = timezone.localdate()
        self.ev = EvenementMedia.objects.create(nom="Groove Circle", date=today)
        self.ev_other = EvenementMedia.objects.create(
            nom="Festival Le Souffleur", date=today - timedelta(days=40)
        )
        # Photos dont le titre reprend le nom de l’événement : l’ancien menu
        # les listait comme cibles, d’où les répétitions.
        MediaItem.objects.create(
            type="photo", titre=str(self.ev), statut="en_attente"
        )
        MediaItem.objects.create(
            type="photo",
            titre="Festival Le Souffleur aux Sables d'Olonne. Eté 2025",
            statut="en_attente",
        )
        self.media = MediaItem.objects.create(
            type="photo", titre="Photo orpheline", statut="en_attente"
        )

    def test_picker_lists_each_event_once(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("admin_medias") + "?statut=en_attente")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("Médias ›", html)
        self.assertNotIn("core › evenementmedia", html)
        self.assertIn("Rattacher à un événement", html)

        import re

        from django.contrib.contenttypes.models import ContentType

        pairs = re.findall(r'value="(\d+)\|(\d+)"', html)
        ct = ContentType.objects.get_for_model(EvenementMedia)
        unique = {(int(ct_id), int(obj_id)) for ct_id, obj_id in pairs}
        self.assertEqual(
            unique,
            {(ct.pk, self.ev.pk), (ct.pk, self.ev_other.pk)},
        )
        option_noms = re.findall(
            r'<option value="\d+\|\d+"[^>]*>\s*([^<]+?)\s*</option>', html
        )
        cards = MediaItem.objects.filter(statut="en_attente").count()
        self.assertEqual(option_noms.count(str(self.ev)), cards)
        self.assertEqual(option_noms.count(str(self.ev_other)), cards)
        self.assertNotIn(
            "Festival Le Souffleur aux Sables d'Olonne. Eté 2025", option_noms
        )

    def test_rattacher_lie_levenement_galerie(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            reverse("admin_media_action", args=[self.media.pk]),
            {
                "action": "rattacher",
                "content_type_id": "999",
                "object_id": str(self.ev.pk),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.media.refresh_from_db()
        self.assertEqual(self.media.evenement_id, self.ev.pk)

    def test_rattacher_ignore_un_media_comme_cible(self):
        self.client.force_login(self.staff)
        other = MediaItem.objects.create(
            pk=90001, type="photo", titre="Leurre", statut="en_attente"
        )
        self.assertFalse(EvenementMedia.objects.filter(pk=other.pk).exists())
        resp = self.client.post(
            reverse("admin_media_action", args=[self.media.pk]),
            {"action": "rattacher", "object_id": str(other.pk)},
        )
        self.assertEqual(resp.status_code, 200)
        self.media.refresh_from_db()
        self.assertIsNone(self.media.evenement_id)
