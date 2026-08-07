from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils.datastructures import MultiValueDict
from PIL import Image

from core.forms import MediaSoumissionForm


class MediaSubmissionFormTests(SimpleTestCase):
    def _form(self, files):
        return MediaSoumissionForm(
            data={
                "type": "photo",
                "evenement_nouveau": "Concert test",
                "soumis_par_nom": "",
                "soumis_par_email": "",
                "url_externe": "",
            },
            files=files,
        )

    def test_multiple_photo_upload_rejects_html_file(self):
        upload = SimpleUploadedFile(
            "attaque.html",
            b"<script>document.location='/admin/'</script>",
            content_type="text/html",
        )

        form = self._form(MultiValueDict({"fichiers_multiples": [upload]}))

        self.assertFalse(form.is_valid())
        self.assertIn("Extension non autorisée", str(form.non_field_errors()))

    def test_photo_upload_rejects_fake_image_content(self):
        upload = SimpleUploadedFile(
            "attaque.jpg",
            b"<script>document.location='/admin/'</script>",
            content_type="image/jpeg",
        )

        form = self._form(MultiValueDict({"fichier": [upload]}))

        self.assertFalse(form.is_valid())
        self.assertIn("image valide", str(form.non_field_errors()))

    def test_multiple_photo_upload_accepts_valid_image(self):
        image_bytes = BytesIO()
        Image.new("RGB", (1, 1)).save(image_bytes, format="PNG")
        upload = SimpleUploadedFile("photo.png", image_bytes.getvalue(), content_type="image/png")

        form = self._form(MultiValueDict({"fichiers_multiples": [upload]}))

        self.assertTrue(form.is_valid(), form.errors)
