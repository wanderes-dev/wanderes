from django.test import TestCase
from django.urls import reverse


class RootRedirectTests(TestCase):
    def test_root_redirects_to_chat(self):
        response = self.client.get("/")

        self.assertRedirects(response, reverse("ai:chat"))
