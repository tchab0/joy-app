from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.mail_spam import (
    contains_seo,
    is_english_seo_spam,
    looks_english,
    looks_foreign_language,
    looks_french,
    looks_gibberish,
)
from core.models import ContactMessage
from users.models import UserNotification

User = get_user_model()


EDWARD = """
Hi,

I checked your website and found a few SEO improvements that can help
increase your Google rankings and generate more quality leads.

I can share a quick SEO proposal with pricing and a strategy tailored
for your business growth.

Let me know if you're interested.

Regards,
Edward
"""


class MailSpamDetectionTests(SimpleTestCase):
    def test_edward_pitch_is_spam(self):
        self.assertTrue(contains_seo(EDWARD))
        self.assertTrue(looks_english(EDWARD))
        self.assertTrue(is_english_seo_spam("SEO proposal", EDWARD))

    def test_french_seo_mention_kept(self):
        body = (
            "Bonjour, nous avons mis à jour le référencement (SEO) de la page "
            "concerts pour votre association en Vendée. Merci, cordialement."
        )
        self.assertTrue(contains_seo(body))
        self.assertFalse(looks_english(body))
        self.assertFalse(is_english_seo_spam("Mise à jour SEO", body))
        self.assertTrue(looks_french(body))
        self.assertFalse(looks_foreign_language(body))

    def test_english_without_seo_kept_for_imap_rule(self):
        body = "Hi, thanks for the concert invitation. Best regards."
        self.assertFalse(contains_seo(body))
        self.assertFalse(is_english_seo_spam("Hello", body))

    def test_english_contact_is_foreign(self):
        body = (
            "Hi, I am looking for a wedding band available on June 15. "
            "Please let me know your pricing. Regards."
        )
        self.assertTrue(looks_english(body))
        self.assertTrue(looks_foreign_language(body))

    def test_cyrillic_is_foreign(self):
        body = "Здравствуйте, хотим заказать оркестр на свадьбу в июне."
        self.assertTrue(looks_foreign_language(body))

    def test_french_contact_kept(self):
        body = (
            "Bonjour, êtes-vous disponibles pour un mariage le 15 juin "
            "à La Roche-sur-Yon ? Merci d’avance."
        )
        self.assertTrue(looks_french(body))
        self.assertFalse(looks_foreign_language(body))

    def test_gibberish_bot_is_foreign(self):
        body = "hntvzoikjvnflxymqfonklwgtddjld"
        self.assertTrue(looks_gibberish(body))
        self.assertTrue(looks_foreign_language(body))

    def test_formtest_english_probe_is_foreign(self):
        body = (
            "Hey there,\n\nQuick test: this message came through your contact "
            "form. If I were a real customer, the clock would already be ticking."
        )
        self.assertTrue(looks_english(body))
        self.assertTrue(looks_foreign_language(body))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SENDING_ENABLED=True,
)
class ContactForeignLanguageFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("contact")

    def test_english_message_discarded(self):
        resp = self.client.post(
            self.url,
            {
                "nom": "Edward",
                "telephone": "",
                "email": "edward@example.com",
                "message": (
                    "Hi, I checked your website and I am looking for a wedding "
                    "band available next month. Please send pricing. Regards."
                ),
                "rgpd": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["success"])
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_gibberish_message_discarded(self):
        resp = self.client.post(
            self.url,
            {
                "nom": "owxpxwmyql",
                "telephone": "",
                "email": "bot@formtests.info",
                "message": "hntvzoikjvnflxymqfonklwgtddjld",
                "rgpd": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["success"])
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_french_message_saved(self):
        resp = self.client.post(
            self.url,
            {
                "nom": "Camille Dupont",
                "telephone": "0600000000",
                "email": "camille@example.com",
                "message": (
                    "Bonjour, êtes-vous disponibles pour un mariage le 15 juin "
                    "à Nantes ? Merci beaucoup."
                ),
                "rgpd": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["success"])
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(ContactMessage.objects.get().email, "camille@example.com")

    def test_admin_purges_existing_foreign_messages(self):
        staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="x",
            is_staff=True,
        )
        foreign = ContactMessage.objects.create(
            kind=ContactMessage.KIND_CONTACT,
            nom="Edward",
            email="edward@example.com",
            message=(
                "Hi, I checked your website and I am looking for a wedding "
                "band available next month. Please send pricing. Regards."
            ),
        )
        kept = ContactMessage.objects.create(
            kind=ContactMessage.KIND_CONTACT,
            nom="Camille",
            email="camille@example.com",
            message="Bonjour, dispo pour un concert en Vendée le mois prochain ?",
        )
        UserNotification.objects.create(
            user=staff,
            title="JOY — Message de contact",
            body="Edward : Hi, I checked your website and I am looking for a wedding band.",
            related_type="contact",
            related_id=foreign.pk,
        )
        UserNotification.objects.create(
            user=staff,
            title="JOY — Message de contact",
            body="Camille : Bonjour, dispo pour un concert en Vendée le mois prochain ?",
            related_type="contact",
            related_id=kept.pk,
        )
        # Orpheline anglaise (message déjà effacé hier).
        UserNotification.objects.create(
            user=staff,
            title="JOY — Message de contact",
            body=(
                "Owen : Hey there, Quick test: this message came through your "
                "contact form. If I were a real customer, the clock would tick."
            ),
            related_type="contact",
            related_id=99999,
        )
        client = Client()
        client.force_login(staff)
        resp = client.get(reverse("admin_contact"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(ContactMessage.objects.get().email, "camille@example.com")
        self.assertEqual(UserNotification.objects.filter(related_type="contact").count(), 1)
        self.assertEqual(
            UserNotification.objects.get(related_type="contact").related_id,
            kept.pk,
        )
