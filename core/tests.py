import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings

from core.models import MediaItem
from core.utils_compression import compresser_media


class MediaCompressionModerationTests(TestCase):
    def setUp(self):
        self.media_root = TemporaryDirectory()
        self.addCleanup(self.media_root.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def create_audio(self):
        return MediaItem.objects.create(
            type="audio",
            titre="Test audio",
            fichier=SimpleUploadedFile("test.wav", b"audio"),
            statut="en_attente",
        )

    @patch("core.utils_compression.subprocess.run")
    def test_does_not_start_after_staff_moderation(self, run):
        media = self.create_audio()
        MediaItem.objects.filter(pk=media.pk).update(
            statut="refuse",
            note_admin="Refus staff",
        )

        compresser_media(media)

        media.refresh_from_db()
        self.assertEqual(media.statut, "refuse")
        self.assertEqual(media.note_admin, "Refus staff")
        run.assert_not_called()

    @patch("core.utils_compression.subprocess.run")
    def test_success_does_not_overwrite_concurrent_publication(self, run):
        media = self.create_audio()

        def publish_during_compression(*args, **kwargs):
            MediaItem.objects.filter(pk=media.pk).update(
                publie=True,
                statut="publie",
            )

        run.side_effect = publish_during_compression

        compresser_media(media)

        media.refresh_from_db()
        self.assertTrue(media.publie)
        self.assertEqual(media.statut, "publie")

    @patch("core.utils_compression.subprocess.run")
    def test_failure_does_not_overwrite_concurrent_refusal(self, run):
        media = self.create_audio()

        def refuse_during_compression(*args, **kwargs):
            MediaItem.objects.filter(pk=media.pk).update(
                statut="refuse",
                note_admin="Refus staff",
            )
            raise subprocess.CalledProcessError(1, "ffmpeg")

        run.side_effect = refuse_during_compression

        compresser_media(media)

        media.refresh_from_db()
        self.assertEqual(media.statut, "refuse")
        self.assertEqual(media.note_admin, "Refus staff")
