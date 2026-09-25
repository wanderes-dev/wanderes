"""Builds a recommendations.scoring.RecommendationRequest from a
scenario's deterministic_request ground-truth dict - shared by
deterministic-only scoring, metamorphic comparisons, and the
intent-vs-scoring-layer diff (comparing what the real pipeline extracted
against this same shape).
"""

from __future__ import annotations

from recommendations.scoring import RecommendationRequest


def build_request(deterministic_request: dict, *, user=None) -> RecommendationRequest:
    d = deterministic_request
    return RecommendationRequest(
        month=d["month"],
        min_temp_c=d.get("min_temp_c"),
        max_temp_c=d.get("max_temp_c"),
        max_cost_of_living=d.get("max_cost_of_living"),
        trip_type=d.get("trip_type"),
        continent=d.get("continent"),
        country=d.get("country"),
        excluded_slugs=frozenset(d.get("excluded_slugs") or ()),
        user=user,
    )
