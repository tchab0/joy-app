from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SharedTemplateTests(TestCase):
    def test_home_renders_for_anonymous_visitors(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)

    def test_home_renders_for_staff(self):
        staff = get_user_model().objects.create_user(
            username="staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
