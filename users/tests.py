from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import AuthChallenge
from .otp import create_challenge, generate_totp_secret, hash_code, verify_challenge, verify_totp
from .phone import normalize_phone
from .roles import (
    user_can_access_member_area,
    user_can_access_planning,
)

User = get_user_model()


class PhoneTests(TestCase):
    def test_normalize_fr_mobile(self):
        self.assertEqual(normalize_phone("06 12 34 56 78"), "+33612345678")
        self.assertEqual(normalize_phone("+33 6 12 34 56 78"), "+33612345678")


class RoleTests(TestCase):
    def test_musician_access(self):
        user = User.objects.create_user(username="m1", password="x", is_musician=True)
        self.assertTrue(user_can_access_planning(user))
        self.assertFalse(user_can_access_member_area(user))

    def test_member_access_with_expiry(self):
        user = User.objects.create_user(
            username="a1",
            password="x",
            is_association_member=True,
            membership_expires_at=date.today() + timedelta(days=30),
        )
        self.assertTrue(user_can_access_member_area(user))
        user.membership_expires_at = date.today() - timedelta(days=1)
        user.save()
        user.clear_role_cache()
        self.assertFalse(user_can_access_member_area(user))


class OTPTests(TestCase):
    def test_email_challenge_roundtrip(self):
        user = User.objects.create_user(
            username="otp1",
            email="otp1@example.com",
            password="x",
        )
        challenge, code = create_challenge(
            user=user,
            purpose=AuthChallenge.Purpose.LOGIN,
            channel=AuthChallenge.Channel.EMAIL,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(verify_challenge(challenge, code))
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_totp_verify(self):
        secret = generate_totp_secret()
        # regenerate by verifying known algorithm against itself
        from .otp import _totp_at

        code = _totp_at(secret)
        self.assertTrue(verify_totp(secret, code))
        self.assertFalse(verify_totp(secret, "000000"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SMS_BACKEND="console",
)
class LoginFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.musician = User.objects.create_user(
            username="joy_m",
            email="m@example.com",
            password="SecretPass123!",
            is_musician=True,
        )
        self.member = User.objects.create_user(
            username="joy_a",
            email="a@example.com",
            password="SecretPass123!",
            is_association_member=True,
        )

    def test_password_login_and_account(self):
        r = self.client.post(
            reverse("account_login"),
            {
                "mode": "password",
                "username": "m@example.com",
                "password": "SecretPass123!",
            },
        )
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("account_home"))
        self.assertEqual(r.status_code, 200)

    def test_planning_requires_musician(self):
        self.client.login(username="joy_a", password="SecretPass123!")
        r = self.client.get(reverse("planning:upcoming_12_months"))
        self.assertIn(r.status_code, (302, 403))

        self.client.login(username="joy_m", password="SecretPass123!")
        r = self.client.get(reverse("planning:upcoming_12_months"))
        self.assertEqual(r.status_code, 200)

    def test_2fa_gate(self):
        self.musician.two_factor_enabled = True
        self.musician.save()
        r = self.client.post(
            reverse("account_login"),
            {
                "mode": "password",
                "username": "joy_m",
                "password": "SecretPass123!",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("account_login_2fa"))

        challenge = AuthChallenge.objects.filter(
            user=self.musician,
            purpose=AuthChallenge.Purpose.TWO_FACTOR,
        ).latest("created_at")
        # Inject known code
        code = "654321"
        challenge.code_hash = hash_code(code)
        challenge.channel = AuthChallenge.Channel.EMAIL
        challenge.save()

        r = self.client.post(
            reverse("account_login_2fa"),
            {
                "action": "verify",
                "challenge_id": str(challenge.id),
                "code": code,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))
