"""Mot de passe provisoire : import CSV + changement imposé à la 1re connexion."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from planning.models import MusicianProfile

User = get_user_model()

TEMP_PASSWORD = "Joy-joy-joy"
NEW_PASSWORD = "TromboneCuivre72"

CSV_HEADER = (
    "Référence commande;Date de la commande;Statut de la commande;"
    "Nom adhérent;Prénom adhérent;Email payeur;Téléphone;e-mail;"
    "Instrument joué\n"
)


def _csv(*rows: str) -> str:
    return CSV_HEADER + "".join(row + "\n" for row in rows)


class ForcePasswordChangeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="jean.dupont",
            email="jean@example.com",
            password=TEMP_PASSWORD,
            first_name="Jean",
            last_name="Dupont",
            is_musician=True,
        )
        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])

    def test_navigation_redirects_to_password_change(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("account_home"))
        self.assertRedirects(
            response,
            reverse("account_password_change") + "?next=" + reverse("account_home"),
        )

    def test_password_change_page_itself_is_reachable(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("account_password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["forced"])

    def test_product_tour_suppressed_while_password_forced(self):
        """Évite la boucle guide → /planning/ → middleware → mot de passe."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("account_password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get("product_tour_config"))

    def test_json_request_gets_403_instead_of_redirect(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("account_notifications"),
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "mot_de_passe_provisoire")

    def test_setting_new_password_unlocks_navigation(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account_password_change"),
            {
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
                "next": reverse("account_home"),
            },
        )
        self.assertRedirects(response, reverse("account_home"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(
            self.client.get(reverse("account_home")).status_code, 200
        )

    def test_cannot_reuse_the_temporary_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account_password_change"),
            {"new_password1": TEMP_PASSWORD, "new_password2": TEMP_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_login_with_temporary_password_then_forced(self):
        response = self.client.post(
            reverse("account_login"),
            {
                "mode": "password",
                "username": "jean@example.com",
                "password": TEMP_PASSWORD,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.request["PATH_INFO"], reverse("account_password_change")
        )

    def test_logout_stays_available(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("account_logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(
            reverse("account_password_change"), response["Location"]
        )

    def test_user_without_flag_is_untouched(self):
        other = User.objects.create_user(
            username="libre", password="SecretPass123!", is_musician=True
        )
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("account_home")).status_code, 200
        )


class ImportAdherentsCsvTests(TestCase):
    def _run(self, content: str, *args: str) -> str:
        out = StringIO()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.csv"
            path.write_text(content, encoding="utf-8")
            call_command("import_adherents_csv", str(path), *args, stdout=out)
        return out.getvalue()

    def test_creates_account_with_prenom_nom_login(self):
        self._run(
            _csv(
                "1;02/12/2025 14:48;Validé;MENGIN;anita;;0626862202;"
                "anita.mengin@example.com;Clarinette"
            )
        )
        user = User.objects.get(email="anita.mengin@example.com")
        self.assertEqual(user.username, "anita.mengin")
        self.assertEqual((user.first_name, user.last_name), ("Anita", "Mengin"))
        self.assertEqual(user.phone, "+33626862202")
        self.assertTrue(user.is_musician)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(TEMP_PASSWORD))
        self.assertEqual(
            MusicianProfile.objects.get(user=user).poste_titulaire,
            MusicianProfile.Poste.CLARINETTE,
        )

    def test_merges_existing_account_matched_by_email(self):
        existing = User.objects.create_user(
            username="musicien42", email="Herve@example.com", password="x"
        )
        self._run(
            _csv(
                "2;02/09/2025 22:51;Validé;BAUDRY;Hervé;;0662482159;"
                "herve@example.com;Trombone"
            )
        )
        self.assertEqual(User.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.username, "herve.baudry")
        self.assertEqual(existing.last_name, "Baudry")
        self.assertTrue(existing.must_change_password)

    def test_merges_existing_account_matched_by_swapped_name(self):
        existing = User.objects.create_user(
            username="old.login",
            email="",
            password="x",
            first_name="Chloe",
            last_name="Brun",
        )
        self._run(
            _csv(
                "3;02/09/2025 11:31;Validé;Brun;Chloe;;0645518659;"
                "chloe@example.com;Chant"
            )
        )
        self.assertEqual(User.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.username, "chloe.brun")
        self.assertEqual(existing.email, "chloe@example.com")

    def test_logged_in_account_keeps_login_and_password(self):
        existing = User.objects.create_user(
            username="stephane",
            email="stephane@example.com",
            password="SecretPass123!",
            first_name="Stéphane",
            last_name="Gallet",
        )
        existing.last_login = timezone.now()
        existing.save(update_fields=["last_login"])

        output = self._run(
            _csv(
                "4;10/09/2025 14:33;Validé;Gallet;Stéphane;;0683276749;"
                "stephane@example.com;Saxophone"
            )
        )
        existing.refresh_from_db()
        self.assertEqual(existing.username, "stephane")
        self.assertTrue(existing.check_password("SecretPass123!"))
        self.assertFalse(existing.must_change_password)
        self.assertIn("déjà connecté", output)

    def test_cancelled_orders_and_duplicates_are_ignored(self):
        output = self._run(
            _csv(
                "5;09/09/2025 16:38;Annulé;Baudry;Hervé;;0662482159;"
                "herve@example.com;Trombone",
                "6;02/09/2025 22:51;Validé;BAUDRY;Hervé;;0662482159;"
                "herve@example.com;Trombone",
                "7;03/09/2025 10:00;Validé;BAUDRY;Hervé;;0662482159;"
                "herve@example.com;Trombone 2",
            )
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertIn("Annulé", output)
        user = User.objects.get()
        self.assertEqual(
            MusicianProfile.objects.get(user=user).poste_titulaire,
            MusicianProfile.Poste.TROMBONE_2,
        )

    def test_ambiguous_instrument_leaves_chair_empty(self):
        output = self._run(
            _csv(
                "8;10/09/2025 15:59;Validé;Pubert;Adrien;;0785439358;"
                "adrien@example.com;Trumpet"
            )
        )
        user = User.objects.get()
        self.assertEqual(
            MusicianProfile.objects.get(user=user).poste_titulaire, ""
        )
        self.assertIn("chaise à affecter", output)

    def test_username_collision_gets_suffix(self):
        User.objects.create_user(
            username="michel.godicheau",
            email="autre@example.com",
            password="x",
            first_name="Michel",
            last_name="Godichot",
        )
        self._run(
            _csv(
                "9;02/12/2025 14:48;Validé;Godicheau;Michel;;0612271012;"
                "michel@example.com;trompette"
            )
        )
        created = User.objects.get(email="michel@example.com")
        self.assertEqual(created.username, "michel.godicheau.2")

    def test_pending_account_outside_csv_also_gets_credentials(self):
        pending = User.objects.create_user(
            username="ancien",
            email="pending@example.com",
            password="x",
            first_name="Didier",
            last_name="Nonin",
            is_musician=True,
        )
        self._run(
            _csv(
                "10;10/09/2025 10:45;Validé;Mengin;Anita;;;"
                "anita@example.com;Clarinette"
            )
        )
        pending.refresh_from_db()
        self.assertEqual(pending.username, "didier.nonin")
        self.assertTrue(pending.must_change_password)
        self.assertTrue(pending.check_password(TEMP_PASSWORD))

    def test_skip_other_pending_option(self):
        pending = User.objects.create_user(
            username="ancien",
            email="pending@example.com",
            password="x",
            first_name="Didier",
            last_name="Nonin",
        )
        self._run(
            _csv(
                "11;10/09/2025 10:45;Validé;Mengin;Anita;;;"
                "anita@example.com;Clarinette"
            ),
            "--skip-other-pending",
        )
        pending.refresh_from_db()
        self.assertEqual(pending.username, "ancien")
        self.assertFalse(pending.must_change_password)

    def test_staff_pending_account_is_protected(self):
        admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="SecretPass123!",
            first_name="Thierry",
            last_name="Chabot",
            is_staff=True,
        )
        output = self._run(
            _csv(
                "12;11/09/2025 20:42;Validé;Chabot;thierry;;0687056502;"
                "admin@example.com;Sax bar si possible"
            )
        )
        admin.refresh_from_db()
        self.assertEqual(admin.username, "admin")
        self.assertTrue(admin.check_password("SecretPass123!"))
        self.assertFalse(admin.must_change_password)
        self.assertIn("compte staff", output)

    def test_dry_run_writes_nothing(self):
        output = self._run(
            _csv(
                "13;10/09/2025 10:45;Validé;Mengin;Anita;;;"
                "anita@example.com;Clarinette"
            ),
            "--dry-run",
        )
        self.assertEqual(User.objects.count(), 0)
        self.assertIn("DRY-RUN", output)

    def test_membership_expiry_option(self):
        self._run(
            _csv(
                "14;10/09/2025 10:45;Validé;Mengin;Anita;;;"
                "anita@example.com;Clarinette"
            ),
            "--membership-expires",
            "2026-08-31",
        )
        user = User.objects.get()
        self.assertTrue(user.is_association_member)
        self.assertEqual(str(user.membership_expires_at), "2026-08-31")
