from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccountLoginTests(TestCase):
    def test_planning_redirects_to_account_login(self):
        planning_url = reverse("planning:upcoming_12_months")
        response = self.client.get(planning_url)

        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={planning_url}",
            fetch_redirect_response=False,
        )

    def test_non_staff_user_can_log_in(self):
        user = get_user_model().objects.create_user(
            username="musician",
            password="test-password",
            is_staff=False,
        )

        response = self.client.post(
            reverse("account_login"),
            {
                "username": user.username,
                "password": "test-password",
                "next": reverse("planning:upcoming_12_months"),
            },
        )

        self.assertRedirects(
            response,
            reverse("planning:upcoming_12_months"),
            fetch_redirect_response=False,
        )
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
