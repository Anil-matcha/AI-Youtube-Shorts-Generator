"""Provider usage normalization and user-supplied cost estimates.

Rates are intentionally never hard-coded: providers change pricing and the
creator can enter current USD-per-million-token values in Settings or via the
JSON API.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Mapping, Optional


def _finite_nonnegative(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number >= 0 else 0.0


def normalize_usage(value: Any) -> Optional[Dict[str, int]]:
    """Normalize OpenAI/Gemini usage objects into input/output token counts."""
    if value is None:
        return None
    source = value if isinstance(value, Mapping) else vars(value) if hasattr(value, "__dict__") else {}
    def read(*names: str, default: Any = 0) -> Any:
        for name in names:
            if name in source:
                return source[name]
            try:
                candidate = getattr(value, name)
            except AttributeError:
                continue
            if candidate is not None:
                return candidate
        return default
    prompt = read("prompt_tokens", "input_tokens", "prompt_token_count")
    completion = read("completion_tokens", "output_tokens", "candidates_token_count", "response_token_count")
    total = read("total_tokens", "total_token_count")
    try:
        input_tokens = max(0, int(prompt or 0))
    except (TypeError, ValueError, OverflowError):
        input_tokens = 0
    try:
        output_tokens = max(0, int(completion or 0))
    except (TypeError, ValueError, OverflowError):
        output_tokens = 0
    try:
        total_tokens = max(0, int(total or input_tokens + output_tokens))
    except (TypeError, ValueError, OverflowError):
        total_tokens = input_tokens + output_tokens
    if not (input_tokens or output_tokens or total_tokens):
        return None
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


def estimate_cost(
    provider: str,
    model: str,
    usage: Any,
    rates: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[float]:
    normalized = normalize_usage(usage)
    if not normalized:
        return None
    config = rates or {}
    provider_rates = config.get(str(provider or "").strip().lower()) or {}
    input_rate = _finite_nonnegative(provider_rates.get("input_usd_per_million"))
    output_rate = _finite_nonnegative(provider_rates.get("output_usd_per_million"))
    if input_rate <= 0 and output_rate <= 0:
        return None
    value = (
        normalized["input_tokens"] * input_rate + normalized["output_tokens"] * output_rate
    ) / 1_000_000.0
    return round(value, 8) if math.isfinite(value) else None


def rates_from_environment() -> Dict[str, Dict[str, float]]:
    """Read optional rates without embedding provider pricing in the app."""
    result: Dict[str, Dict[str, float]] = {}
    for provider in ("openai", "gemini", "muapi"):
        result[provider] = {
            "input_usd_per_million": _finite_nonnegative(
                os.getenv(f"SHORTS_{provider.upper()}_INPUT_USD_PER_MILLION", "0")
            ),
            "output_usd_per_million": _finite_nonnegative(
                os.getenv(f"SHORTS_{provider.upper()}_OUTPUT_USD_PER_MILLION", "0")
            ),
        }
    return result
