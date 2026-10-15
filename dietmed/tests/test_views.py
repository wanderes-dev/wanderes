from django.test import TestCase
from django.urls import reverse


class RedirectToPartnerTests(TestCase):
    def test_forwards_the_code_to_the_partner_url(self):
        response = self.client.get(reverse("dietmed:redirect"), {"codigo": "ABC123"})

        self.assertRedirects(
            response,
            "https://external.dietmed.pt/fishing.asp?codigo=ABC123",
            fetch_redirect_response=False,
        )

    def test_encodes_a_code_with_special_characters(self):
        response = self.client.get(reverse("dietmed:redirect"), {"codigo": "a&b=c"})

        self.assertRedirects(
            response,
            "https://external.dietmed.pt/fishing.asp?codigo=a%26b%3Dc",
            fetch_redirect_response=False,
        )

    def test_strips_surrounding_whitespace(self):
        response = self.client.get(reverse("dietmed:redirect"), {"codigo": "  XYZ  "})

        self.assertRedirects(
            response,
            "https://external.dietmed.pt/fishing.asp?codigo=XYZ",
            fetch_redirect_response=False,
        )

    def test_missing_code_is_a_bad_request_not_a_blind_redirect(self):
        response = self.client.get(reverse("dietmed:redirect"))

        self.assertEqual(response.status_code, 400)

    def test_blank_code_is_also_a_bad_request(self):
        response = self.client.get(reverse("dietmed:redirect"), {"codigo": "   "})

        self.assertEqual(response.status_code, 400)
