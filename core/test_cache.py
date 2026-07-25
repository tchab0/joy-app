from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.views import home


class PersonalizedPageCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def test_home_response_is_rendered_for_each_user(self):
        def personalized_render(request, template_name, context):
            return HttpResponse(request.user.username)

        alice_request = self.factory.get("/")
        alice_request.user = SimpleNamespace(username="alice")
        bob_request = self.factory.get("/")
        bob_request.user = SimpleNamespace(username="bob")

        with patch("core.views.render", side_effect=personalized_render) as render_mock:
            alice_response = home(alice_request)
            bob_response = home(bob_request)

        self.assertEqual(alice_response.content, b"alice")
        self.assertEqual(bob_response.content, b"bob")
        self.assertEqual(render_mock.call_count, 2)
