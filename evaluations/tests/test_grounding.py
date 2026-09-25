from django.test import TestCase

from evaluations.grounding import run_grounding_checks
from recommendations.scoring import ScoredDestination
from travel.models import Destination


def _destination():
    return Destination.objects.create(
        slug="lisboa-pt",
        name="Lisbon",
        country="Portugal",
        latitude=38.72,
        longitude=-9.14,
        trip_type="city",
        cost_of_living=3,
        best_season="Mar-Oct",
        worst_season="Dec-Feb",
        short_description="A coastal capital.",
        points_of_interest=[],
    )


def _scored(destination):
    return ScoredDestination(
        destination=destination,
        avg_high_c=22.0,
        avg_low_c=15.0,
        preference_fit=0.0,
        budget_fit=0.0,
        temperature_fit=0.0,
        repetition_penalty=0.0,
        score=0.0,
    )


class GroundingChecksTests(TestCase):
    def setUp(self):
        self.scored = [_scored(_destination())]

    def _names(self, results):
        return {r.name: r.passed for r in results}

    def test_clean_reply_passes_everything(self):
        reply = "Lisbon is a wonderful choice - great food, walkable streets, and mild weather."
        results = run_grounding_checks(reply, self.scored)
        self.assertTrue(all(r.passed for r in results))

    def test_winner_not_mentioned_fails(self):
        reply = "Here's a lovely place to visit with great weather this time of year."
        results = run_grounding_checks(reply, self.scored)
        checks = self._names(results)
        self.assertFalse(checks["winner_mentioned"])

    def test_live_price_claim_is_caught(self):
        reply = "Lisbon is great! Prices starting at $89/night right now."
        results = run_grounding_checks(reply, self.scored)
        self.assertFalse(self._names(results)["no_live_price_claim"])

    def test_availability_claim_is_caught(self):
        reply = "Lisbon is great, and I checked availability - there are currently available rooms."
        results = run_grounding_checks(reply, self.scored)
        self.assertFalse(self._names(results)["no_availability_claim"])

    def test_provider_consultation_claim_is_caught(self):
        reply = "Lisbon works well - I checked booking.com and found some good options."
        results = run_grounding_checks(reply, self.scored)
        self.assertFalse(self._names(results)["no_provider_consultation_claim"])

    def test_fabricated_rating_is_caught(self):
        reply = "Lisbon is rated 4.8/5 with 1200 reviews, a fantastic choice."
        results = run_grounding_checks(reply, self.scored)
        self.assertFalse(self._names(results)["no_fabricated_rating_or_review"])

    def test_no_scored_destinations_never_fails_winner_check(self):
        results = run_grounding_checks("I can't help with that specific request.", [])
        self.assertTrue(self._names(results)["winner_mentioned"])

    def test_country_mention_counts_as_winner_mentioned(self):
        reply = "Portugal has some wonderful spots for this time of year."
        results = run_grounding_checks(reply, self.scored)
        self.assertTrue(self._names(results)["winner_mentioned"])
