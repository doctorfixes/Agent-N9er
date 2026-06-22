"""OpenRouter LLM client — execute tasks using any model via OpenRouter API.

Handles model selection, token counting, cost estimation, and actual
LLM calls. All other services use this as the execution backbone.
"""

import os
import logging
import time
from dataclasses import dataclass

import httpx

from shared.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("openrouter")

_llm_breaker = CircuitBreaker(name="openrouter", failure_threshold=5, recovery_timeout=30.0)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MARKUP_MULTIPLIER = float(os.getenv("MARKUP_MULTIPLIER", "3.0"))

MODEL_TIERS = {
    "budget": {
        "model": "anthropic/claude-haiku-4-5-20251001",
        "input_cost_per_m": 0.80,
        "output_cost_per_m": 4.00,
        "max_tokens": 8192,
        "label": "Quick tasks, classification, simple Q&A",
    },
    "standard": {
        "model": "anthropic/claude-sonnet-4-6",
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "max_tokens": 16384,
        "label": "Code generation, analysis, writing",
    },
    "premium": {
        "model": "anthropic/claude-opus-4-8",
        "input_cost_per_m": 15.00,
        "output_cost_per_m": 75.00,
        "max_tokens": 32768,
        "label": "Complex reasoning, architecture, research",
    },
    "deepseek": {
        "model": "deepseek/deepseek-chat-v3-0324",
        "input_cost_per_m": 0.30,
        "output_cost_per_m": 0.90,
        "max_tokens": 8192,
        "label": "High-volume, cost-sensitive tasks",
    },
}


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    finish_reason: str


@dataclass
class CostEstimate:
    model: str
    tier: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    quoted_price_usd: float
    markup_multiplier: float


def estimate_tokens(text: str) -> int:
    if not text:
        return 1
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii_chars = len(text) - ascii_chars
    tokens = ascii_chars / 4.0 + non_ascii_chars / 1.5
    return max(1, int(tokens))


def estimate_cost(
    prompt: str,
    tier: str = "standard",
    expected_output_tokens: int = 2000,
) -> CostEstimate:
    model_info = MODEL_TIERS.get(tier, MODEL_TIERS["standard"])
    input_tokens = estimate_tokens(prompt)
    input_cost = (input_tokens / 1_000_000) * model_info["input_cost_per_m"]
    output_cost = (expected_output_tokens / 1_000_000) * model_info["output_cost_per_m"]
    total_cost = input_cost + output_cost
    quoted = round(total_cost * MARKUP_MULTIPLIER, 4)

    return CostEstimate(
        model=model_info["model"],
        tier=tier,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=expected_output_tokens,
        estimated_cost_usd=round(total_cost, 6),
        quoted_price_usd=quoted,
        markup_multiplier=MARKUP_MULTIPLIER,
    )


def select_tier(complexity: str, budget_constraint: str = "normal") -> str:
    if budget_constraint == "minimum":
        return "deepseek"
    tier_map = {
        "trivial": "budget",
        "simple": "budget",
        "moderate": "standard",
        "complex": "standard",
        "expert": "premium",
    }
    return tier_map.get(complexity, "standard")


async def complete(
    messages: list[dict],
    tier: str = "standard",
    model_override: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.3,
) -> LLMResponse:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not configured")

    model_info = MODEL_TIERS.get(tier, MODEL_TIERS["standard"])
    model = model_override or model_info["model"]
    max_tok = max_tokens or model_info["max_tokens"]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://agentn9ner.com",
        "X-Title": "Agent N9er",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tok,
        "temperature": temperature,
    }

    if _llm_breaker.state == "open":
        raise CircuitOpenError(
            f"Circuit '{_llm_breaker.name}' is open after {_llm_breaker._failure_count} failures"
        )

    from shared.config import OPENROUTER_TIMEOUT
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        await _llm_breaker._on_success()
    except Exception:
        await _llm_breaker._on_failure()
        raise

    elapsed_ms = (time.monotonic() - start) * 1000

    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    actual_model_info = model_info
    if model_override:
        for tier_info in MODEL_TIERS.values():
            if tier_info["model"] == model_override:
                actual_model_info = tier_info
                break

    input_cost = (input_tokens / 1_000_000) * actual_model_info.get("input_cost_per_m", 3.0)
    output_cost = (output_tokens / 1_000_000) * actual_model_info.get("output_cost_per_m", 15.0)
    total_cost = input_cost + output_cost

    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    finish_reason = choice.get("finish_reason", "unknown")

    logger.info(
        "LLM call: model=%s tokens=%d+%d cost=$%.4f latency=%.0fms",
        model, input_tokens, output_tokens, total_cost, elapsed_ms,
    )

    return LLMResponse(
        content=content,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(total_cost, 6),
        latency_ms=round(elapsed_ms, 1),
        finish_reason=finish_reason,
    )


async def list_models() -> list[dict]:
    if not OPENROUTER_API_KEY:
        return list(MODEL_TIERS.values())

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{OPENROUTER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
    except httpx.RequestError:
        logger.warning("Failed to fetch OpenRouter models, using defaults")
        return list(MODEL_TIERS.values())
