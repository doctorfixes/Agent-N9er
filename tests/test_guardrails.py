"""Tests for the guardrails module — content filtering, spending limits, and safety checks."""

import os
import pytest

os.environ.setdefault("MAX_SINGLE_TASK_USD", "500.0")
os.environ.setdefault("MAX_DAILY_SPEND_USD", "2000.0")
os.environ.setdefault("REQUIRE_APPROVAL_ABOVE_USD", "100.0")

from shared.guardrails import (
    check_task_content,
    check_spending_limits,
    check_execution_allowed,
    check_output_safety,
    run_all_checks,
)


class TestTaskContentFiltering:
    def test_clean_task_passes(self):
        violations = check_task_content("Build a REST API", "Create CRUD endpoints for user management")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) == 0

    def test_malware_request_blocked(self):
        violations = check_task_content("Write malware for Windows", "Create a keylogger")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1
        assert any("malware" in v.reason for v in blocked)

    def test_phishing_blocked(self):
        violations = check_task_content("Create phishing page", "Clone a bank login page")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1

    def test_ddos_tool_blocked(self):
        violations = check_task_content("Build DDoS tool", "denial of service attack script")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1

    def test_fake_reviews_blocked(self):
        violations = check_task_content("Generate fake reviews", "Astroturfing campaign for product")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1

    def test_platform_tos_violation_blocked(self):
        violations = check_task_content("Create fake account on Upwork", "Sockpuppet profile")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1

    def test_high_risk_domain_warns(self):
        violations = check_task_content("Write medical advice article", "Diagnosis guide for patients")
        warnings = [v for v in violations if v.severity == "warning"]
        assert len(warnings) >= 1

    def test_legal_advice_warns(self):
        violations = check_task_content("Provide legal advice", "Contract dispute resolution")
        warnings = [v for v in violations if v.severity == "warning"]
        assert len(warnings) >= 1

    def test_skills_checked_too(self):
        violations = check_task_content("Programming project", "", "malware development")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1

    def test_copyright_infringement_blocked(self):
        violations = check_task_content("Crack software license", "Create a keygen")
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1


class TestSpendingLimits:
    def test_within_limits(self):
        violations = check_spending_limits(50.0, 100.0)
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) == 0

    def test_exceeds_single_task_limit(self):
        violations = check_spending_limits(600.0)
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1
        assert any("single-task" in v.reason for v in blocked)

    def test_exceeds_daily_limit(self):
        violations = check_spending_limits(100.0, 1950.0)
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1
        assert any("daily" in v.reason for v in blocked)

    def test_requires_approval_above_threshold(self):
        violations = check_spending_limits(150.0)
        approvals = [v for v in violations if v.severity == "requires_approval"]
        assert len(approvals) >= 1

    def test_small_amount_auto_approved(self):
        violations = check_spending_limits(10.0)
        approvals = [v for v in violations if v.severity == "requires_approval"]
        assert len(approvals) == 0


class TestOutputSafety:
    def test_clean_output_passes(self):
        output = "Here is the REST API implementation with proper error handling..."
        violations = check_output_safety(output)
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) == 0

    def test_ssn_pattern_warned(self):
        output = "The user's SSN is 123-45-6789"
        violations = check_output_safety(output)
        warnings = [v for v in violations if v.severity == "warning"]
        assert len(warnings) >= 1

    def test_credential_pattern_warned(self):
        output = "password: mysecretpass123"
        violations = check_output_safety(output)
        warnings = [v for v in violations if v.severity == "warning"]
        assert len(warnings) >= 1

    def test_harmful_content_blocked(self):
        output = "Here is the malware code that exploits the vulnerability..."
        violations = check_output_safety(output)
        blocked = [v for v in violations if v.severity == "blocked"]
        assert len(blocked) >= 1


class TestRunAllChecks:
    def test_clean_task_approved(self):
        result = run_all_checks(
            title="Build a dashboard",
            description="React dashboard with charts",
            quoted_price_usd=25.0,
        )
        assert result["decision"] == "approved"
        assert result["blocked_count"] == 0

    def test_prohibited_task_blocked(self):
        result = run_all_checks(
            title="Create ransomware",
            description="Encrypt files and demand payment",
            quoted_price_usd=50.0,
        )
        assert result["decision"] == "blocked"
        assert result["blocked_count"] >= 1

    def test_expensive_task_needs_approval(self):
        result = run_all_checks(
            title="Build a web app",
            description="Full-stack application",
            quoted_price_usd=200.0,
        )
        assert result["decision"] == "requires_approval"

    def test_high_risk_warns(self):
        result = run_all_checks(
            title="Write financial advice article",
            description="Investment recommendations for retirement",
            quoted_price_usd=15.0,
        )
        assert result["decision"] == "approved_with_warnings"
        assert result["warning_count"] >= 1
