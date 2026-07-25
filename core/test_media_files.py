import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.management.commands.purger_originaux import Command
from core.models import MediaItem
from core.utils_compression import compresser_media


class MediaFileSafetyTests(TestCase):
    def setUp(self):
        self.media_dir = TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.media_dir.cleanup()

    def create_media(self, path, **overrides):
        values = {
            "type": "photo",
            "titre": path,
            "fichier": path,
            "statut": "en_attente",
        }
        values.update(overrides)
        return MediaItem.objects.create(**values)

    def write_media_file(self, relative_path, content=b"original"):
        path = Path(self.media_dir.name) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_same_basename_gets_distinct_sidecars_and_independent_cleanup(self):
        first = self.create_media("medias/2025/01/IMG_001.jpg")
        second = self.create_media("medias/2026/07/IMG_001.jpg")

        first_sidecar = first.chemin_compresse_destination()
        second_sidecar = second.chemin_compresse_destination()
        self.assertNotEqual(first_sidecar, second_sidecar)

        first_sidecar.parent.mkdir(parents=True, exist_ok=True)
        first_sidecar.write_bytes(b"first")
        second_sidecar.write_bytes(b"second")

        with self.captureOnCommitCallbacks(execute=True):
            first.delete()

        self.assertFalse(first_sidecar.exists())
        self.assertEqual(second_sidecar.read_bytes(), b"second")

    def test_failed_compression_does_not_leave_partial_sidecar(self):
        media = self.create_media(
            "medias/2026/07/interview.wav",
            type="audio",
        )
        self.write_media_file(media.fichier.name)
        destination = media.chemin_compresse_destination()

        def fail_after_writing(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, command)

        with patch("core.utils_compression.subprocess.run", side_effect=fail_after_writing):
            compresser_media(media)

        media.refresh_from_db()
        self.assertFalse(destination.exists())
        self.assertEqual(media.statut, "en_attente")
        self.assertIn("Erreur compression", media.note_admin)
        self.assertEqual(list(destination.parent.glob(".*.m4a")), [])

    def test_purge_keeps_original_when_database_switch_fails(self):
        media = self.create_media(
            "medias/2026/07/recording.wav",
            type="audio",
            statut="publie",
            publie=True,
        )
        original = self.write_media_file(media.fichier.name)
        sidecar = media.chemin_compresse_destination()
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_bytes(b"compressed")

        with patch.object(MediaItem, "save", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                Command()._remplacer_par_compresse(media)

        self.assertEqual(original.read_bytes(), b"original")
