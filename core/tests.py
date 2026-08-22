from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.template import Context, Engine
from django.test import SimpleTestCase, override_settings

from core.utils_compression import compresser_media


class MediaGalleryVideoTests(SimpleTestCase):
    def _render_gallery(self, video):
        engine = Engine(
            dirs=[settings.BASE_DIR / "templates"],
            loaders=[
                (
                    "django.template.loaders.locmem.Loader",
                    {"base.html": "{% block content %}{% endblock %}"},
                ),
                "django.template.loaders.filesystem.Loader",
            ],
        )
        template = engine.get_template("core/medias.html")
        return template.render(Context({
            "videos": [video],
            "groupes_photos": [],
            "audios": [],
            "pdfs": [],
        }))

    def test_uploaded_video_is_rendered_with_native_player(self):
        video = SimpleNamespace(
            titre="Vidéo locale",
            url_externe="",
            fichier=SimpleNamespace(url="/media/medias/video.mp4"),
        )

        rendered = self._render_gallery(video)

        self.assertIn("<video controls", rendered)
        self.assertIn('src="/media/medias/video.mp4"', rendered)
        self.assertNotIn('<iframe src=""', rendered)

    @patch("core.utils_compression.subprocess.run")
    def test_compressed_video_uses_browser_compatible_codec(self, run):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            media = SimpleNamespace(
                fichier=SimpleNamespace(path=f"{media_root}/source.mov"),
                type="video",
                statut="en_attente",
                publie=False,
                save=Mock(),
            )

            compresser_media(media)

        command = run.call_args.args[0]
        self.assertIn("libx264", command)
        self.assertIn("yuv420p", command)
        self.assertNotIn("libx265", command)
