from django.test import SimpleTestCase

from core.mail_spam import contains_seo, is_english_seo_spam, looks_english


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

    def test_english_without_seo_kept(self):
        body = "Hi, thanks for the concert invitation. Best regards."
        self.assertFalse(contains_seo(body))
        self.assertFalse(is_english_seo_spam("Hello", body))
