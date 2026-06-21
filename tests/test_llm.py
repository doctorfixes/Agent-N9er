"""Tests for shared/llm.py — cost estimation, tier selection, token estimation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.llm import estimate_cost, estimate_tokens, select_tier, MODEL_TIERS


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
        assert est.markup_multiplier == 3.0

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
        assert abs(est.quoted_price_usd - est.estimated_cost_usd * 3.0) < 0.01

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
