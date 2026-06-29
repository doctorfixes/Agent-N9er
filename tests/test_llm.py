"""Tests for shared/llm.py — cost estimation, tier selection, token estimation, completions."""

import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.llm import (
    MODEL_TIERS,
    LLMResponse,
    _parse_openai_content,
    _split_system_messages,
    complete,
    estimate_cost,
    estimate_tokens,
    get_active_provider,
    get_model_tiers,
    has_available_provider,
    list_models,
    select_tier,
)


class TestEstimateTokens:
    def test_basic_text(self):
        tokens = estimate_tokens("Hello world this is a test")
        assert tokens > 0

    def test_empty_string(self):
        assert estimate_tokens("") == 1

    def test_long_text(self):
        text = "word " * 10000
        tokens = estimate_tokens(text)
        assert tokens > 1000


class TestEstimateCost:
    def test_standard_tier(self):
        est = estimate_cost("Build a REST API", tier="standard")
        assert est.tier == "standard"
        assert est.model == MODEL_TIERS["standard"]["model"]
        assert est.estimated_cost_usd > 0
        assert est.quoted_price_usd > est.estimated_cost_usd
        assert est.markup_multiplier == 8.0

    def test_budget_tier_cheaper(self):
        budget = estimate_cost("Fix a typo", tier="budget", expected_output_tokens=500)
        standard = estimate_cost("Fix a typo", tier="standard", expected_output_tokens=500)
        assert budget.estimated_cost_usd < standard.estimated_cost_usd

    def test_premium_tier_most_expensive(self):
        premium = estimate_cost("Design system architecture", tier="premium", expected_output_tokens=5000)
        standard = estimate_cost("Design system architecture", tier="standard", expected_output_tokens=5000)
        assert premium.estimated_cost_usd > standard.estimated_cost_usd

    def test_markup_applied(self):
        est = estimate_cost("Test task", tier="standard")
        assert abs(est.quoted_price_usd - est.estimated_cost_usd * 8.0) < 0.01

    def test_deepseek_tier(self):
        est = estimate_cost("Quick task", tier="deepseek")
        assert est.model == MODEL_TIERS["deepseek"]["model"]
        assert est.estimated_cost_usd > 0


class TestSelectTier:
    def test_trivial_gets_budget(self):
        assert select_tier("trivial") == "budget"

    def test_simple_gets_budget(self):
        assert select_tier("simple") == "budget"

    def test_moderate_gets_standard(self):
        assert select_tier("moderate") == "standard"

    def test_complex_gets_standard(self):
        assert select_tier("complex") == "standard"

    def test_expert_gets_premium(self):
        assert select_tier("expert") == "premium"

    def test_minimum_budget_override(self):
        assert select_tier("expert", budget_constraint="minimum") == "deepseek"

    def test_unknown_defaults_standard(self):
        assert select_tier("unknown_level") == "standard"


class TestProviderSelection:
    def test_no_provider_when_no_keys(self, monkeypatch):
        for key in [
            "LLM_PROVIDER",
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "GEMINI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)
        assert get_active_provider() is None
        assert has_available_provider() is False

    def test_auto_selects_anthropic_when_configured(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert get_active_provider() == "anthropic"
        assert has_available_provider() is True

    def test_explicit_provider_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert get_active_provider() == "openai"

    def test_model_tiers_change_by_provider(self):
        anthropic_tiers = get_model_tiers("anthropic")
        openai_tiers = get_model_tiers("openai")
        assert anthropic_tiers["standard"]["model"] != MODEL_TIERS["standard"]["model"]
        assert openai_tiers["budget"]["model"] == "gpt-4o-mini"

    def test_minimum_budget_uses_budget_for_direct_provider(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert select_tier("expert", budget_constraint="minimum") == "budget"


class TestParseOpenAIContent:
    def test_string_content(self):
        assert _parse_openai_content("hello world") == "hello world"

    def test_list_of_text_blocks(self):
        content = [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ]
        assert _parse_openai_content(content) == "Hello world"

    def test_list_with_non_text_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "url": "http://example.com/img.png"},
            {"type": "text", "text": " world"},
        ]
        assert _parse_openai_content(content) == "Hello world"

    def test_empty_list(self):
        assert _parse_openai_content([]) == ""

    def test_other_type_returns_empty(self):
        assert _parse_openai_content(12345) == ""
        assert _parse_openai_content(None) == ""
        assert _parse_openai_content({"key": "val"}) == ""


class TestSplitSystemMessages:
    def test_no_system_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        system, non_system = _split_system_messages(messages)
        assert system == ""
        assert len(non_system) == 2

    def test_one_system_message(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, non_system = _split_system_messages(messages)
        assert system == "You are helpful."
        assert len(non_system) == 1
        assert non_system[0]["role"] == "user"

    def test_multiple_system_messages(self):
        messages = [
            {"role": "system", "content": "Part 1"},
            {"role": "system", "content": "Part 2"},
            {"role": "user", "content": "Hello"},
        ]
        system, non_system = _split_system_messages(messages)
        assert "Part 1" in system
        assert "Part 2" in system
        assert len(non_system) == 1

    def test_empty_system_content_filtered(self):
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "Hello"},
        ]
        system, non_system = _split_system_messages(messages)
        assert system == ""
        assert len(non_system) == 1


class TestComplete:
    async def test_no_provider_raises(self, monkeypatch):
        for key in [
            "LLM_PROVIDER", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
            "GEMINI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(ValueError, match="No LLM provider configured"):
            await complete([{"role": "user", "content": "Hello"}])

    async def test_openrouter_complete(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Hello from OpenRouter!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("shared.llm.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await complete(
                [{"role": "user", "content": "Hi"}],
                tier="standard",
            )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from OpenRouter!"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.finish_reason == "stop"
        assert result.cost_usd >= 0

    async def test_anthropic_complete(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-ant-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Anthropic!"}],
            "usage": {"input_tokens": 8, "output_tokens": 4},
            "stop_reason": "end_turn",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("shared.llm.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await complete(
                [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hi"},
                ],
                tier="standard",
            )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Anthropic!"
        assert result.input_tokens == 8
        assert result.output_tokens == 4

    async def test_complete_with_model_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("shared.llm.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await complete(
                [{"role": "user", "content": "Hi"}],
                model_override="custom/my-model",
            )
        assert result.model == "custom/my-model"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["model"] == "custom/my-model"


class TestListModels:
    async def test_list_models_no_provider(self, monkeypatch):
        for key in [
            "LLM_PROVIDER", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
            "GEMINI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        result = await list_models()
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_list_models_openrouter(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "model-a", "name": "Model A"},
                {"id": "model-b", "name": "Model B"},
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch("shared.llm.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await list_models()
        assert len(result) == 2
        assert result[0]["id"] == "model-a"

    async def test_list_models_openrouter_request_error_falls_back(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        with patch("shared.llm.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await list_models()
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_list_models_non_openrouter_provider(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        result = await list_models()
        assert isinstance(result, list)
        assert len(result) > 0
