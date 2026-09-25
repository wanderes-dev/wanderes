"""Rough cost estimation for a full-pipeline evaluation run.

Neither `AIProvider.generate_structured_reply` (returns a plain dict)
nor `.stream_reply` (raw text chunks) exposes token usage at any of the
call sites `ai.orchestration` actually uses - the same gap
`analytics/instrumentation.py` already documents for production
telemetry. So this estimates cost from prompt/reply character length
rather than real token counts. Labelled everywhere as an estimate, never
presented as an exact bill.
"""

from __future__ import annotations

from dataclasses import dataclass

# gpt-4o-mini pricing as of writing (USD per 1M tokens). This module
# doesn't look the price up dynamically - update these if AI_MODEL
# changes to something else.
_PRICE_PER_1M_INPUT_TOKENS_USD = 0.15
_PRICE_PER_1M_OUTPUT_TOKENS_USD = 0.60

# ~4 characters/token is the standard rough English-text approximation
# (matches OpenAI's own tokenizer documentation) - an order-of-magnitude
# estimate, not meant to be exact.
_CHARS_PER_TOKEN = 4.0

# A recommendation-flow scenario makes up to 3 real calls
# (extract_intent + extract_climate_budget_signal + the final
# explanation stream); most other flows make fewer. This tracker doesn't
# know ahead of time which branch will fire, so it charges a flat
# per-scenario estimate calibrated to that worst case rather than trying
# to predict the branch - meaning the total is a conservative
# (over-, not under-) estimate.
_ESTIMATED_CALLS_PER_PIPELINE_SCENARIO = 3
_ESTIMATED_PROMPT_OVERHEAD_CHARS = 1800  # system prompt + schema + a few history turns, rough


@dataclass
class CostTracker:
    model_name: str
    pipeline_scenarios: int = 0
    judge_calls: int = 0
    estimated_input_chars: int = 0
    estimated_output_chars: int = 0

    def record_pipeline_call(self, *, scenario_message: str, reply: str) -> None:
        self.pipeline_scenarios += 1
        self.estimated_input_chars += (
            _ESTIMATED_PROMPT_OVERHEAD_CHARS + len(scenario_message)
        ) * _ESTIMATED_CALLS_PER_PIPELINE_SCENARIO
        self.estimated_output_chars += len(reply) + 200  # + the two structured-JSON replies

    def record_judge_call(self, *, scenario_message: str, reply: str) -> None:
        self.judge_calls += 1
        self.estimated_input_chars += 600 + len(scenario_message) + len(reply)
        self.estimated_output_chars += 300

    @property
    def estimated_input_tokens(self) -> float:
        return self.estimated_input_chars / _CHARS_PER_TOKEN

    @property
    def estimated_output_tokens(self) -> float:
        return self.estimated_output_chars / _CHARS_PER_TOKEN

    @property
    def estimated_usd(self) -> float:
        return (
            self.estimated_input_tokens / 1_000_000 * _PRICE_PER_1M_INPUT_TOKENS_USD
            + self.estimated_output_tokens / 1_000_000 * _PRICE_PER_1M_OUTPUT_TOKENS_USD
        )

    def to_json(self) -> dict:
        return {
            "model_name": self.model_name,
            "pipeline_scenarios": self.pipeline_scenarios,
            "judge_calls": self.judge_calls,
            "estimated_input_tokens": round(self.estimated_input_tokens),
            "estimated_output_tokens": round(self.estimated_output_tokens),
            "estimated_usd": round(self.estimated_usd, 4),
            "note": (
                "Rough estimate from prompt/reply character length, not real token "
                "counts - neither generate_structured_reply nor stream_reply expose "
                "usage data today."
            ),
        }
