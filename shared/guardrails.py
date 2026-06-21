import os
import logging
import re

logger = logging.getLogger("guardrails")

MAX_SINGLE_TASK_USD = float(os.getenv("MAX_SINGLE_TASK_USD", "500.0"))
MAX_DAILY_SPEND_USD = float(os.getenv("MAX_DAILY_SPEND_USD", "2000.0"))
REQUIRE_APPROVAL_ABOVE_USD = float(os.getenv("REQUIRE_APPROVAL_ABOVE_USD", "100.0"))
AUTO_EXECUTE_ENABLED = os.getenv("AUTO_EXECUTE_ENABLED", "true").lower() == "true"

PROHIBITED_CONTENT = [
    "malware", "ransomware", "exploit", "zero-day", "0day",
    "phishing", "spyware", "keylogger", "trojan", "rootkit",
    "ddos", "denial of service", "botnet",
    "hack into", "break into", "bypass security", "crack password",
    "steal data", "data theft", "exfiltrate",
    "fake identity", "forged document", "counterfeit",
    "money laundering", "fraud scheme", "ponzi",
    "deepfake", "impersonat", "catfish",
    "child exploitation", "csam", "underage",
    "weapon", "explosive", "bomb",
    "drug synthesis", "narcotics", "illegal substance",
    "harassment campaign", "doxxing", "stalk",
    "spam campaign", "mass email", "email bomb",
    "copyright infring", "pirat", "crack software", "keygen",
    "academic fraud", "write my exam", "fake diploma",
    "review manipulation", "fake review", "astroturf",
    "scrape personal data", "surveillance", "spy on",
]

PLATFORM_TOS_VIOLATIONS = [
    "fake account", "bot account", "sockpuppet",
    "bid manipulation", "shill bid",
    "circumvent platform", "off-platform payment",
    "fake portfolio", "fabricated experience",
]

HIGH_RISK_CATEGORIES = [
    "medical advice", "legal advice", "financial advice",
    "investment recommendation", "tax advice",
    "therapy", "counseling", "diagnosis",
]


class GuardrailViolation:
    def __init__(self, violation_type: str, reason: str, severity: str = "blocked"):
        self.violation_type = violation_type
        self.reason = reason
        self.severity = severity

    def to_dict(self):
        return {
            "violation_type": self.violation_type,
            "reason": self.reason,
            "severity": self.severity,
        }


def check_task_content(title: str, description: str = "", skills: str = "") -> list[GuardrailViolation]:
    text = f"{title} {description} {skills}".lower()
    violations = []

    for term in PROHIBITED_CONTENT:
        if term in text:
            violations.append(GuardrailViolation(
                "prohibited_content",
                f"Task contains prohibited content: '{term}'",
                "blocked",
            ))

    for term in PLATFORM_TOS_VIOLATIONS:
        if term in text:
            violations.append(GuardrailViolation(
                "tos_violation",
                f"Task may violate platform terms of service: '{term}'",
                "blocked",
            ))

    for term in HIGH_RISK_CATEGORIES:
        if term in text:
            violations.append(GuardrailViolation(
                "high_risk",
                f"Task involves high-risk domain requiring disclaimers: '{term}'",
                "warning",
            ))

    return violations


def check_spending_limits(
    quoted_price_usd: float,
    daily_spent_usd: float = 0,
) -> list[GuardrailViolation]:
    violations = []

    if quoted_price_usd > MAX_SINGLE_TASK_USD:
        violations.append(GuardrailViolation(
            "spending_limit",
            f"Quoted price ${quoted_price_usd:.2f} exceeds single-task limit of ${MAX_SINGLE_TASK_USD:.2f}",
            "blocked",
        ))

    if daily_spent_usd + quoted_price_usd > MAX_DAILY_SPEND_USD:
        violations.append(GuardrailViolation(
            "daily_limit",
            f"Would exceed daily spending limit of ${MAX_DAILY_SPEND_USD:.2f} "
            f"(already spent ${daily_spent_usd:.2f}, this task ${quoted_price_usd:.2f})",
            "blocked",
        ))

    if quoted_price_usd > REQUIRE_APPROVAL_ABOVE_USD:
        violations.append(GuardrailViolation(
            "approval_required",
            f"Task quote ${quoted_price_usd:.2f} exceeds auto-approval threshold of ${REQUIRE_APPROVAL_ABOVE_USD:.2f}",
            "requires_approval",
        ))

    return violations


def check_execution_allowed() -> list[GuardrailViolation]:
    if not AUTO_EXECUTE_ENABLED:
        return [GuardrailViolation(
            "auto_execute_disabled",
            "Automatic execution is disabled — manual approval required for all tasks",
            "requires_approval",
        )]
    return []


def check_output_safety(output: str) -> list[GuardrailViolation]:
    violations = []
    text_lower = output.lower()

    sensitive_patterns = [
        (r'\b\d{3}-\d{2}-\d{4}\b', "SSN-like pattern"),
        (r'\b\d{16}\b', "credit card number pattern"),
        (r'(?:password|secret|api.?key)\s*[:=]\s*\S+', "exposed credential"),
    ]
    for pattern, label in sensitive_patterns:
        if re.search(pattern, text_lower):
            violations.append(GuardrailViolation(
                "sensitive_output",
                f"Output may contain sensitive data: {label}",
                "warning",
            ))

    for term in PROHIBITED_CONTENT[:15]:
        if term in text_lower:
            violations.append(GuardrailViolation(
                "unsafe_output",
                f"Output contains potentially harmful content: '{term}'",
                "blocked",
            ))
            break

    return violations


def run_all_checks(
    title: str = "",
    description: str = "",
    quoted_price_usd: float = 0,
    daily_spent_usd: float = 0,
) -> dict:
    content_violations = check_task_content(title, description)
    spending_violations = check_spending_limits(quoted_price_usd, daily_spent_usd)
    exec_violations = check_execution_allowed()

    all_violations = content_violations + spending_violations + exec_violations
    blocked = [v for v in all_violations if v.severity == "blocked"]
    warnings = [v for v in all_violations if v.severity == "warning"]
    approvals = [v for v in all_violations if v.severity == "requires_approval"]

    if blocked:
        decision = "blocked"
    elif approvals:
        decision = "requires_approval"
    elif warnings:
        decision = "approved_with_warnings"
    else:
        decision = "approved"

    result = {
        "decision": decision,
        "violations": [v.to_dict() for v in all_violations],
        "blocked_count": len(blocked),
        "warning_count": len(warnings),
        "approval_count": len(approvals),
    }

    if blocked:
        logger.warning("Task BLOCKED: %s — %s", title[:60], blocked[0].reason)
    elif warnings:
        logger.info("Task approved with %d warnings: %s", len(warnings), title[:60])

    return result
