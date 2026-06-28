"""LLM client with OpenRouter and direct provider support."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("llm")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

MARKUP_MULTIPLIER = float(os.getenv("MARKUP_MULTIPLIER", "3.0"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

PROVIDER_ORDER = ["openrouter", "anthropic", "openai", "azure", "gemini"]

BASE_MODEL_TIERS = {
    "budget": {
        "input_cost_per_m": 0.80,
        "output_cost_per_m": 4.00,
        "max_tokens": 8192,
        "label": "Quick tasks, classification, simple Q&A",
        "models": {
            "openrouter": "anthropic/claude-haiku-4.5",
            "anthropic": "claude-3-5-haiku-latest",
            "openai": "gpt-4o-mini",
            "azure": os.getenv("AZURE_OPENAI_BUDGET_DEPLOYMENT", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")),
            "gemini": "gemini-2.5-flash",
        },
    },
    "standard": {
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "max_tokens": 16384,
        "label": "Code generation, analysis, writing",
        "models": {
            "openrouter": "anthropic/claude-sonnet-4.6",
            "anthropic": "claude-sonnet-4-0",
            "openai": "gpt-4.1",
            "azure": os.getenv("AZURE_OPENAI_STANDARD_DEPLOYMENT", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")),
            "gemini": "gemini-2.5-flash",
        },
    },
    "premium": {
        "input_cost_per_m": 15.00,
        "output_cost_per_m": 75.00,
        "max_tokens": 32768,
        "label": "Complex reasoning, architecture, research",
        "models": {
            "openrouter": "anthropic/claude-opus-4.8",
            "anthropic": "claude-opus-4-1",
            "openai": "gpt-5",
            "azure": os.getenv("AZURE_OPENAI_PREMIUM_DEPLOYMENT", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5")),
            "gemini": "gemini-2.5-pro",
        },
    },
    "deepseek": {
        "input_cost_per_m": 0.30,
        "output_cost_per_m": 0.90,
        "max_tokens": 8192,
        "label": "High-volume, cost-sensitive tasks",
        "models": {
            "openrouter": "deepseek/deepseek-chat",
            "anthropic": "claude-3-5-haiku-latest",
            "openai": "gpt-4o-mini",
            "azure": os.getenv("AZURE_OPENAI_BUDGET_DEPLOYMENT", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")),
            "gemini": "gemini-2.5-flash",
        },
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


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _is_provider_configured(provider: str) -> bool:
    if provider == "openrouter":
        return bool(_get_env("OPENROUTER_API_KEY"))
    if provider == "anthropic":
        return bool(_get_env("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(_get_env("OPENAI_API_KEY"))
    if provider == "azure":
        return bool(_get_env("AZURE_OPENAI_API_KEY") and _get_env("AZURE_OPENAI_ENDPOINT"))
    if provider == "gemini":
        return bool(_get_env("GEMINI_API_KEY"))
    return False


def get_active_provider() -> str | None:
    configured = _get_env("LLM_PROVIDER").lower() or "auto"
    providers = PROVIDER_ORDER if configured == "auto" else [configured]
    for provider in providers:
        if _is_provider_configured(provider):
            return provider
    return None


def has_available_provider() -> bool:
    return get_active_provider() is not None


def _resolve_tier(tier: str, provider: str | None = None) -> str:
    active_provider = provider or get_active_provider() or "openrouter"
    if tier == "deepseek" and active_provider != "openrouter":
        return "budget"
    return tier if tier in BASE_MODEL_TIERS else "standard"


def get_model_tiers(provider: str | None = None) -> dict[str, dict[str, Any]]:
    active_provider = provider or get_active_provider() or "openrouter"
    tiers: dict[str, dict[str, Any]] = {}
    for tier_name, info in BASE_MODEL_TIERS.items():
        resolved_tier = _resolve_tier(tier_name, active_provider)
        source = BASE_MODEL_TIERS[resolved_tier]
        tiers[tier_name] = {
            "model": source["models"].get(active_provider, source["models"]["openrouter"]),
            "input_cost_per_m": source["input_cost_per_m"],
            "output_cost_per_m": source["output_cost_per_m"],
            "max_tokens": source["max_tokens"],
            "label": info["label"],
        }
    return tiers


MODEL_TIERS = get_model_tiers("openrouter")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_cost(
    prompt: str,
    tier: str = "standard",
    expected_output_tokens: int = 2000,
) -> CostEstimate:
    resolved_tier = _resolve_tier(tier)
    model_info = get_model_tiers().get(resolved_tier, get_model_tiers()["standard"])
    input_tokens = estimate_tokens(prompt)
    input_cost = (input_tokens / 1_000_000) * model_info["input_cost_per_m"]
    output_cost = (expected_output_tokens / 1_000_000) * model_info["output_cost_per_m"]
    total_cost = input_cost + output_cost
    quoted = round(total_cost * MARKUP_MULTIPLIER, 4)

    return CostEstimate(
        model=model_info["model"],
        tier=resolved_tier,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=expected_output_tokens,
        estimated_cost_usd=round(total_cost, 6),
        quoted_price_usd=quoted,
        markup_multiplier=MARKUP_MULTIPLIER,
    )


def select_tier(complexity: str, budget_constraint: str = "normal") -> str:
    if budget_constraint == "minimum":
        active_provider = get_active_provider()
        return "deepseek" if active_provider in (None, "openrouter") else "budget"
    tier_map = {
        "trivial": "budget",
        "simple": "budget",
        "moderate": "standard",
        "complex": "standard",
        "expert": "premium",
    }
    return tier_map.get(complexity, "standard")


def _parse_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def _split_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = []
    non_system = []
    for message in messages:
        if message.get("role") == "system":
            system_parts.append(message.get("content", ""))
        else:
            non_system.append(message)
    return "\n\n".join(part for part in system_parts if part), non_system


async def _openrouter_complete(
    client: httpx.AsyncClient,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, dict]:
    resp = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": "Bearer " + _get_env("OPENROUTER_API_KEY"),
            "Content-Type": "application/json",
            "HTTP-Referer": "https://agentn9er.com",
            "X-Title": "Agent N9er",
        },
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    choice = data.get("choices", [{}])[0]
    return data, {
        "content": _parse_openai_content(choice.get("message", {}).get("content", "")),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "finish_reason": choice.get("finish_reason", "unknown"),
    }


async def _openai_complete(
    client: httpx.AsyncClient,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, dict]:
    resp = await client.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={
            "Authorization": "Bearer " + _get_env("OPENAI_API_KEY"),
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    choice = data.get("choices", [{}])[0]
    return data, {
        "content": _parse_openai_content(choice.get("message", {}).get("content", "")),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "finish_reason": choice.get("finish_reason", "unknown"),
    }


async def _azure_complete(
    client: httpx.AsyncClient,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, dict]:
    endpoint = _get_env("AZURE_OPENAI_ENDPOINT").rstrip("/")
    api_version = _get_env("AZURE_OPENAI_API_VERSION") or "2024-10-21"
    resp = await client.post(
        f"{endpoint}/openai/deployments/{model}/chat/completions?api-version={api_version}",
        headers={
            "api-key": _get_env("AZURE_OPENAI_API_KEY"),
            "Content-Type": "application/json",
        },
        json={
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    choice = data.get("choices", [{}])[0]
    return data, {
        "content": _parse_openai_content(choice.get("message", {}).get("content", "")),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "finish_reason": choice.get("finish_reason", "unknown"),
    }


async def _anthropic_complete(
    client: httpx.AsyncClient,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, dict]:
    system_text, chat_messages = _split_system_messages(messages)
    anthropic_messages = [
        {
            "role": "assistant" if msg.get("role") == "assistant" else "user",
            "content": [{"type": "text", "text": msg.get("content", "")}],
        }
        for msg in chat_messages
    ]
    payload = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_text:
        payload["system"] = system_text
    resp = await client.post(
        f"{ANTHROPIC_BASE_URL}/messages",
        headers={
            "x-api-key": _get_env("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    blocks = data.get("content", [])
    return data, {
        "content": "".join(block.get("text", "") for block in blocks if block.get("type") == "text"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "finish_reason": data.get("stop_reason", "unknown"),
    }


async def _gemini_complete(
    client: httpx.AsyncClient,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, dict]:
    system_text, chat_messages = _split_system_messages(messages)
    contents = [
        {
            "role": "model" if msg.get("role") == "assistant" else "user",
            "parts": [{"text": msg.get("content", "")}],
        }
        for msg in chat_messages
    ]
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}
    resp = await client.post(
        f"{GEMINI_BASE_URL}/models/{model}:generateContent",
        params={"key": _get_env("GEMINI_API_KEY")},
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usageMetadata", {})
    candidate = data.get("candidates", [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    return data, {
        "content": "".join(part.get("text", "") for part in parts),
        "input_tokens": usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
        "finish_reason": candidate.get("finishReason", "unknown"),
    }


async def complete(
    messages: list[dict],
    tier: str = "standard",
    model_override: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.3,
) -> LLMResponse:
    provider = get_active_provider()
    if not provider:
        raise ValueError("No LLM provider configured")

    resolved_tier = _resolve_tier(tier, provider)
    model_info = get_model_tiers(provider).get(resolved_tier, get_model_tiers(provider)["standard"])
    model = model_override or model_info["model"]
    max_tok = max_tokens or model_info["max_tokens"]

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=120.0) as client:
        if provider == "openrouter":
            _, result = await _openrouter_complete(client, messages, model, max_tok, temperature)
        elif provider == "anthropic":
            _, result = await _anthropic_complete(client, messages, model, max_tok, temperature)
        elif provider == "openai":
            _, result = await _openai_complete(client, messages, model, max_tok, temperature)
        elif provider == "azure":
            _, result = await _azure_complete(client, messages, model, max_tok, temperature)
        elif provider == "gemini":
            _, result = await _gemini_complete(client, messages, model, max_tok, temperature)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    elapsed_ms = (time.monotonic() - start) * 1000
    input_cost = (result["input_tokens"] / 1_000_000) * model_info.get("input_cost_per_m", 3.0)
    output_cost = (result["output_tokens"] / 1_000_000) * model_info.get("output_cost_per_m", 15.0)
    total_cost = input_cost + output_cost

    logger.info(
        "LLM call: provider=%s model=%s tokens=%d+%d cost=$%.4f latency=%.0fms",
        provider,
        model,
        result["input_tokens"],
        result["output_tokens"],
        total_cost,
        elapsed_ms,
    )

    return LLMResponse(
        content=result["content"],
        model=model,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        cost_usd=round(total_cost, 6),
        latency_ms=round(elapsed_ms, 1),
        finish_reason=result["finish_reason"],
    )


async def list_models() -> list[dict]:
    provider = get_active_provider()
    if provider == "openrouter":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{OPENROUTER_BASE_URL}/models",
                    headers={"Authorization": "Bearer " + _get_env("OPENROUTER_API_KEY")},
                )
                resp.raise_for_status()
                return resp.json().get("data", [])
        except httpx.RequestError:
            logger.warning("Failed to fetch OpenRouter models, using defaults")
    return list(get_model_tiers(provider).values())
