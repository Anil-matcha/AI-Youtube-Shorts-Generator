"""Usage normalization and creator-supplied pricing tests."""

from __future__ import annotations

from shorts_generator.costs import estimate_cost, normalize_usage


class _Usage:
    prompt_tokens = 1000
    completion_tokens = 500
    total_tokens = 1500


def test_normalize_openai_usage_and_estimate_cost() -> None:
    usage = normalize_usage(_Usage())
    assert usage == {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}
    assert estimate_cost(
        "openai",
        "model",
        usage,
        {"openai": {"input_usd_per_million": 2.0, "output_usd_per_million": 4.0}},
    ) == 0.004


def test_unknown_rates_remain_unknown() -> None:
    assert estimate_cost("gemini", "model", {"input_tokens": 10, "output_tokens": 10}) is None
