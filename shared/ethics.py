"""
Ethics guardrails for Agent N9er.

Screens projects and deliverables to prevent participation in harmful,
deceptive, illegal, or exploitative work.
"""

import re
import logging

logger = logging.getLogger("ethics")

BLOCKED_CATEGORIES = {
    "malware": [
        r"malware", r"ransomware", r"keylogger", r"trojan", r"rootkit",
        r"exploit\s+kit", r"rat\b.*remote\s+access", r"botnet", r"spyware",
        r"ddos", r"denial.of.service", r"brute\s*force\s+attack",
        r"crack(ing|er)\b(?!.*interview)", r"bypass\s+(security|authentication|firewall)",
    ],
    "fraud_and_scams": [
        r"phishing", r"scam\s+(page|site|email|template)",
        r"fake\s+(bank|paypal|login|identity|passport|id\b|document|diploma|certificate)",
        r"carding", r"credit\s+card\s+fraud", r"money\s+launder",
        r"ponzi", r"pyramid\s+scheme", r"counterfeit",
        r"clone\s+(site|website|page).*(?:bank|paypal|login)",
    ],
    "academic_dishonesty": [
        r"write\s+my\s+(essay|thesis|dissertation|homework|assignment|exam)\b",
        r"take\s+my\s+(exam|test|quiz|online\s+class)\b",
        r"do\s+my\s+(homework|assignment|coursework)\b",
        r"ghost\s*writ(e|ing)\s+(essay|thesis|dissertation|research\s+paper)\b",
        r"plagiari(sm|ze)", r"cheat(ing)?\s+(on\s+)?(exam|test|quiz)",
        r"buy\s+(essay|thesis|assignment|diploma)\b",
    ],
    "deception_and_manipulation": [
        r"fake\s+review", r"astroturf", r"shill\s+(post|review|comment)",
        r"bot\s+farm", r"click\s+farm", r"sock\s*puppet",
        r"impersonat(e|ion|ing)", r"catfish",
        r"deepfake(?!.*detect)", r"misinformation\s+campaign",
        r"spam\s+(bot|campaign|tool|software|email)",
        r"mass\s+unsolicited\s+(email|message|sms)",
    ],
    "illegal_content": [
        r"child\s+(porn|exploitation|abuse\s+material)",
        r"\bcsam\b", r"drug\s+(marketplace|shop|deal)",
        r"dark\s*web\s+(market|shop|store)",
        r"illegal\s+(gambling|betting)\s+(site|platform)",
        r"weapon(s)?\s+(sale|shop|market|3d\s+print)",
        r"human\s+traffick",
    ],
    "privacy_violation": [
        r"dox(x)?ing", r"stalk(er|ing)\s+(app|tool|software)",
        r"spy\s+on\s+(spouse|partner|employee|someone)",
        r"track\s+(someone|person|wife|husband|partner)\s+without",
        r"scrape\s+(personal|private|user)\s+data\s+without",
        r"harvest\s+(email|phone|personal)\s+data",
    ],
    "copyright_piracy": [
        r"crack(ed)?\s+(software|game|app|license)",
        r"pirat(e|ed|ing)\s+(movie|music|software|game|book|content)",
        r"torrent\s+(site|platform|index).*build",
        r"bypass\s+(drm|copy\s*protect|license\s+key)",
        r"\bkeygen\b", r"nulled\s+(script|theme|plugin)",
    ],
    "exploitation": [
        r"sweatshop", r"forced\s+labor",
        r"pay.*below\s+minimum\s+wage",
        r"predatory\s+lending\s+(site|app|platform)",
    ],
}

BLOCKED_FLAT = []
for patterns in BLOCKED_CATEGORIES.values():
    BLOCKED_FLAT.extend(patterns)
_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_FLAT]

_CATEGORY_COMPILED = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in BLOCKED_CATEGORIES.items()
}


def screen_project(title: str, description: str, skills: str = "") -> dict:
    """
    Screen a project for ethical violations.

    Returns:
        {
            "allowed": True/False,
            "flags": ["category1", ...],
            "reasons": ["matched pattern details"],
        }
    """
    text = f"{title} {description} {skills}".strip()
    if not text:
        return {"allowed": True, "flags": [], "reasons": []}

    flags = []
    reasons = []

    for category, patterns in _CATEGORY_COMPILED.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                if category not in flags:
                    flags.append(category)
                reasons.append(f"{category}: matched '{match.group()}' in project text")
                break

    allowed = len(flags) == 0

    if not allowed:
        logger.warning(
            "Project BLOCKED by ethics screen: title=%r flags=%s",
            title[:80], flags,
        )

    return {"allowed": allowed, "flags": flags, "reasons": reasons}


def screen_deliverable(content: str) -> dict:
    """
    Screen generated deliverable content before sending to client.
    Catches cases where LLM output contains harmful content even if
    the project title seemed benign.
    """
    if not content:
        return {"allowed": True, "flags": [], "reasons": []}

    flags = []
    reasons = []

    dangerous_output = [
        re.compile(r"<script[^>]*>.*?(document\.cookie|eval\(|fetch\()", re.IGNORECASE | re.DOTALL),
        re.compile(r"(sql\s+injection|xss\s+payload|exploit\s+code)", re.IGNORECASE),
        re.compile(r"(rm\s+-rf\s+/|format\s+c:|:(){ :\|:& };:)", re.IGNORECASE),
        re.compile(r"(password|credential|api.key|secret).*=\s*['\"][^'\"]{8,}", re.IGNORECASE),
    ]

    for pattern in dangerous_output:
        match = pattern.search(content)
        if match:
            flags.append("dangerous_output")
            reasons.append(f"Deliverable contains potentially dangerous content: '{match.group()[:60]}'")
            break

    return {"allowed": len(flags) == 0, "flags": flags, "reasons": reasons}


TRANSPARENCY_NOTICE = (
    "Disclosure: This work was completed with AI-assisted development tools. "
    "All code has been reviewed and tested for quality and correctness."
)


def add_transparency_notice(deliverable: str, format: str = "text") -> str:
    """Append a transparency disclosure to deliverables."""
    if format == "markdown":
        return f"{deliverable}\n\n---\n\n*{TRANSPARENCY_NOTICE}*\n"
    elif format == "html":
        return f"{deliverable}\n<hr><p><em>{TRANSPARENCY_NOTICE}</em></p>\n"
    return f"{deliverable}\n\n{TRANSPARENCY_NOTICE}\n"
