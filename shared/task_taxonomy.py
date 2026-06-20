"""
AI Task Taxonomy — Top 20 most valuable AI tasks ranked by economic leverage.

Tasks are organized into four value tiers based on cross-task performance,
cost-efficiency, and enterprise adoption patterns.
"""

from enum import Enum
from typing import Optional
import re


class ValueTier(str, Enum):
    HIGHEST_LEVERAGE = "highest_leverage"
    HIGH_ROI = "high_roi"
    OPERATIONAL = "operational"
    CREATIVE_TECHNICAL = "creative_technical"


class TaskCategory(str, Enum):
    CODE_GENERATION = "code_generation"
    COMPLEX_REASONING = "complex_reasoning"
    DATA_ANALYSIS = "data_analysis"
    RESEARCH_SYNTHESIS = "research_synthesis"
    WORKFLOW_AUTOMATION = "workflow_automation"

    CUSTOMER_SUPPORT = "customer_support"
    CONTENT_GENERATION = "content_generation"
    TRANSLATION = "translation"
    SEARCH_RAG = "search_rag"
    TASK_EXTRACTION = "task_extraction"

    MEETING_SUMMARIZATION = "meeting_summarization"
    EMAIL_TRIAGE = "email_triage"
    PROJECT_PLANNING = "project_planning"
    DATA_CLEANING = "data_cleaning"
    DOCUMENT_COMPARISON = "document_comparison"

    IMAGE_GENERATION = "image_generation"
    VIDEO_SCRIPTING = "video_scripting"
    API_DOCUMENTATION = "api_documentation"
    UNIT_TEST_GENERATION = "unit_test_generation"
    PRODUCT_MOCKUPS = "product_mockups"

    UNCATEGORIZED = "uncategorized"


TASK_DEFINITIONS = {
    TaskCategory.CODE_GENERATION: {
        "rank": 1,
        "tier": ValueTier.HIGHEST_LEVERAGE,
        "label": "Code Generation",
        "description": "Generate, refactor, debug, and review code across languages and frameworks",
        "leverage_score": 10.0,
        "cost_tier": "mid",
        "keywords": [
            "code", "implement", "function", "class", "refactor", "debug",
            "build", "develop", "program", "script", "module", "feature",
            "fix bug", "pull request", "merge", "commit", "deploy code",
            "api endpoint", "backend", "frontend", "full-stack",
        ],
    },
    TaskCategory.COMPLEX_REASONING: {
        "rank": 2,
        "tier": ValueTier.HIGHEST_LEVERAGE,
        "label": "Complex Reasoning & Planning",
        "description": "Multi-step logical reasoning, strategic planning, and decision analysis",
        "leverage_score": 9.5,
        "cost_tier": "mid",
        "keywords": [
            "reason", "analyze", "plan", "strategy", "decide", "evaluate",
            "compare", "tradeoff", "architecture", "design system",
            "optimize", "solve", "proof", "logic", "deduce", "infer",
        ],
    },
    TaskCategory.DATA_ANALYSIS: {
        "rank": 3,
        "tier": ValueTier.HIGHEST_LEVERAGE,
        "label": "Data Analysis & Interpretation",
        "description": "Analyze datasets, generate insights, build visualizations, and statistical modeling",
        "leverage_score": 9.0,
        "cost_tier": "mid",
        "keywords": [
            "data", "analysis", "metrics", "dashboard", "report", "statistics",
            "trend", "insight", "visualization", "chart", "graph", "kpi",
            "performance", "benchmark", "forecast", "model",
        ],
    },
    TaskCategory.RESEARCH_SYNTHESIS: {
        "rank": 4,
        "tier": ValueTier.HIGHEST_LEVERAGE,
        "label": "Research Synthesis",
        "description": "Summarize, compare, and extract insights from large corpora and documentation",
        "leverage_score": 8.5,
        "cost_tier": "mid",
        "keywords": [
            "research", "summarize", "synthesis", "literature", "survey",
            "review paper", "compare", "findings", "study", "evidence",
            "bibliography", "citation", "abstract", "corpus",
        ],
    },
    TaskCategory.WORKFLOW_AUTOMATION: {
        "rank": 5,
        "tier": ValueTier.HIGHEST_LEVERAGE,
        "label": "Automating Repetitive Workflows",
        "description": "Automate high-volume repetitive tasks with fast instruction-following models",
        "leverage_score": 8.0,
        "cost_tier": "low",
        "keywords": [
            "automate", "workflow", "pipeline", "batch", "schedule",
            "recurring", "trigger", "webhook", "integration", "cron",
            "etl", "migration", "bulk", "process",
        ],
    },
    TaskCategory.CUSTOMER_SUPPORT: {
        "rank": 6,
        "tier": ValueTier.HIGH_ROI,
        "label": "Customer Support Automation",
        "description": "Handle customer queries, route tickets, and generate responses at scale",
        "leverage_score": 7.5,
        "cost_tier": "low",
        "keywords": [
            "customer", "support", "ticket", "helpdesk", "faq",
            "respond", "complaint", "inquiry", "chat", "service desk",
        ],
    },
    TaskCategory.CONTENT_GENERATION: {
        "rank": 7,
        "tier": ValueTier.HIGH_ROI,
        "label": "Content Generation at Scale",
        "description": "Writing, rewriting, summarizing content for marketing, docs, and communications",
        "leverage_score": 7.0,
        "cost_tier": "low",
        "keywords": [
            "write", "content", "blog", "article", "copy", "rewrite",
            "edit", "proofread", "headline", "social media", "press release",
            "newsletter", "marketing", "seo",
        ],
    },
    TaskCategory.TRANSLATION: {
        "rank": 8,
        "tier": ValueTier.HIGH_ROI,
        "label": "Translation & Multilingual Operations",
        "description": "Translate text, localize content, and manage multilingual communications",
        "leverage_score": 6.5,
        "cost_tier": "low",
        "keywords": [
            "translate", "translation", "localize", "multilingual",
            "language", "i18n", "l10n", "internationalization",
        ],
    },
    TaskCategory.SEARCH_RAG: {
        "rank": 9,
        "tier": ValueTier.HIGH_ROI,
        "label": "Search + RAG Pipelines",
        "description": "Build and run retrieval-augmented generation for knowledge-intensive queries",
        "leverage_score": 6.5,
        "cost_tier": "mid",
        "keywords": [
            "search", "rag", "retrieval", "embedding", "vector",
            "knowledge base", "index", "semantic", "query", "lookup",
        ],
    },
    TaskCategory.TASK_EXTRACTION: {
        "rank": 10,
        "tier": ValueTier.HIGH_ROI,
        "label": "Task Extraction from Documents",
        "description": "Turn unstructured text into structured actions, entities, and metadata",
        "leverage_score": 6.0,
        "cost_tier": "low",
        "keywords": [
            "extract", "parse", "structure", "entity", "ner",
            "classify", "categorize", "tag", "label", "annotation",
            "unstructured", "ocr", "form",
        ],
    },
    TaskCategory.MEETING_SUMMARIZATION: {
        "rank": 11,
        "tier": ValueTier.OPERATIONAL,
        "label": "Meeting Summarization",
        "description": "Summarize meetings, extract action items, and generate notes",
        "leverage_score": 5.5,
        "cost_tier": "low",
        "keywords": [
            "meeting", "minutes", "action items", "summary", "standup",
            "retro", "agenda", "notes", "transcript", "call",
        ],
    },
    TaskCategory.EMAIL_TRIAGE: {
        "rank": 12,
        "tier": ValueTier.OPERATIONAL,
        "label": "Email Drafting & Triage",
        "description": "Draft emails, prioritize inbox, and route messages to appropriate teams",
        "leverage_score": 5.0,
        "cost_tier": "low",
        "keywords": [
            "email", "draft", "reply", "inbox", "triage",
            "priority", "forward", "cc", "thread", "mail",
        ],
    },
    TaskCategory.PROJECT_PLANNING: {
        "rank": 13,
        "tier": ValueTier.OPERATIONAL,
        "label": "Project Planning",
        "description": "Create project plans, timelines, resource allocation, and task breakdowns",
        "leverage_score": 5.0,
        "cost_tier": "mid",
        "keywords": [
            "project plan", "timeline", "milestone", "gantt", "sprint",
            "roadmap", "backlog", "epic", "story", "resource",
            "stakeholder", "deliverable",
        ],
    },
    TaskCategory.DATA_CLEANING: {
        "rank": 14,
        "tier": ValueTier.OPERATIONAL,
        "label": "Data Cleaning & Transformation",
        "description": "Clean, normalize, deduplicate, and transform datasets at scale",
        "leverage_score": 4.5,
        "cost_tier": "low",
        "keywords": [
            "clean", "transform", "normalize data", "deduplicate",
            "format", "convert", "csv", "json", "xml", "schema",
            "validate data", "sanitize",
        ],
    },
    TaskCategory.DOCUMENT_COMPARISON: {
        "rank": 15,
        "tier": ValueTier.OPERATIONAL,
        "label": "Document Comparison & Summarization",
        "description": "Compare documents for changes, review contracts, check compliance",
        "leverage_score": 4.5,
        "cost_tier": "mid",
        "keywords": [
            "compare", "diff", "contract", "policy", "compliance",
            "audit", "review document", "legal", "regulation",
            "changelog", "version",
        ],
    },
    TaskCategory.IMAGE_GENERATION: {
        "rank": 16,
        "tier": ValueTier.CREATIVE_TECHNICAL,
        "label": "Image Generation for Marketing",
        "description": "Generate marketing visuals, illustrations, and branded imagery",
        "leverage_score": 4.0,
        "cost_tier": "mid",
        "keywords": [
            "image", "generate image", "illustration", "visual",
            "graphic", "banner", "thumbnail", "logo", "brand",
        ],
    },
    TaskCategory.VIDEO_SCRIPTING: {
        "rank": 17,
        "tier": ValueTier.CREATIVE_TECHNICAL,
        "label": "Video Script Generation",
        "description": "Write video scripts, storyboards, and content for video production pipelines",
        "leverage_score": 3.5,
        "cost_tier": "low",
        "keywords": [
            "video", "script", "storyboard", "scene", "narration",
            "voiceover", "clip", "footage", "production",
        ],
    },
    TaskCategory.API_DOCUMENTATION: {
        "rank": 18,
        "tier": ValueTier.CREATIVE_TECHNICAL,
        "label": "API Documentation",
        "description": "Generate and maintain API docs, schemas, and developer guides",
        "leverage_score": 3.5,
        "cost_tier": "low",
        "keywords": [
            "api doc", "documentation", "openapi", "swagger", "schema",
            "endpoint doc", "developer guide", "reference", "spec",
        ],
    },
    TaskCategory.UNIT_TEST_GENERATION: {
        "rank": 19,
        "tier": ValueTier.CREATIVE_TECHNICAL,
        "label": "Unit Test Generation",
        "description": "Generate unit tests, integration tests, and test fixtures",
        "leverage_score": 3.5,
        "cost_tier": "low",
        "keywords": [
            "test", "unit test", "integration test", "pytest", "jest",
            "coverage", "assert", "mock", "fixture", "spec",
            "test case", "tdd",
        ],
    },
    TaskCategory.PRODUCT_MOCKUPS: {
        "rank": 20,
        "tier": ValueTier.CREATIVE_TECHNICAL,
        "label": "Product Mockups & Concepting",
        "description": "Create wireframes, UI mockups, and product concept designs",
        "leverage_score": 3.0,
        "cost_tier": "mid",
        "keywords": [
            "mockup", "wireframe", "prototype", "ui design", "ux",
            "figma", "layout", "component", "design system",
        ],
    },
    TaskCategory.UNCATEGORIZED: {
        "rank": 99,
        "tier": ValueTier.OPERATIONAL,
        "label": "Uncategorized",
        "description": "Tasks that don't match a known category",
        "leverage_score": 1.0,
        "cost_tier": "mid",
        "keywords": [],
    },
}


COST_MULTIPLIERS = {
    "low": 0.3,
    "mid": 1.0,
    "high": 3.0,
}


TIER_ORDER = [
    ValueTier.HIGHEST_LEVERAGE,
    ValueTier.HIGH_ROI,
    ValueTier.OPERATIONAL,
    ValueTier.CREATIVE_TECHNICAL,
]


AGENT_SPECIALIZATIONS = {
    "code_specialist": {
        "primary": [
            TaskCategory.CODE_GENERATION,
            TaskCategory.UNIT_TEST_GENERATION,
            TaskCategory.API_DOCUMENTATION,
        ],
        "secondary": [
            TaskCategory.WORKFLOW_AUTOMATION,
            TaskCategory.DATA_CLEANING,
            TaskCategory.SEARCH_RAG,
        ],
        "confidence_boost": 0.15,
        "secondary_boost": 0.05,
    },
    "research_analyst": {
        "primary": [
            TaskCategory.RESEARCH_SYNTHESIS,
            TaskCategory.DATA_ANALYSIS,
            TaskCategory.COMPLEX_REASONING,
        ],
        "secondary": [
            TaskCategory.DOCUMENT_COMPARISON,
            TaskCategory.MEETING_SUMMARIZATION,
            TaskCategory.PROJECT_PLANNING,
        ],
        "confidence_boost": 0.15,
        "secondary_boost": 0.05,
    },
    "content_creator": {
        "primary": [
            TaskCategory.CONTENT_GENERATION,
            TaskCategory.VIDEO_SCRIPTING,
            TaskCategory.TRANSLATION,
        ],
        "secondary": [
            TaskCategory.EMAIL_TRIAGE,
            TaskCategory.CUSTOMER_SUPPORT,
            TaskCategory.IMAGE_GENERATION,
        ],
        "confidence_boost": 0.15,
        "secondary_boost": 0.05,
    },
    "operations_agent": {
        "primary": [
            TaskCategory.WORKFLOW_AUTOMATION,
            TaskCategory.TASK_EXTRACTION,
            TaskCategory.DATA_CLEANING,
        ],
        "secondary": [
            TaskCategory.EMAIL_TRIAGE,
            TaskCategory.MEETING_SUMMARIZATION,
            TaskCategory.CUSTOMER_SUPPORT,
        ],
        "confidence_boost": 0.15,
        "secondary_boost": 0.05,
    },
    "generalist": {
        "primary": [],
        "secondary": [],
        "confidence_boost": 0.0,
        "secondary_boost": 0.0,
    },
}


def classify_task(objective: str, inputs: Optional[dict] = None) -> dict:
    text = objective.lower()
    if inputs:
        text += " " + " ".join(str(v).lower() for v in inputs.values())

    best_category = TaskCategory.UNCATEGORIZED
    best_score = 0.0

    for category, defn in TASK_DEFINITIONS.items():
        if category == TaskCategory.UNCATEGORIZED:
            continue
        score = 0.0
        for keyword in defn["keywords"]:
            if keyword in text:
                score += len(keyword.split())
        if score > best_score:
            best_score = score
            best_category = category

    defn = TASK_DEFINITIONS[best_category]
    return {
        "category": best_category.value,
        "tier": defn["tier"].value,
        "rank": defn["rank"],
        "label": defn["label"],
        "leverage_score": defn["leverage_score"],
        "cost_tier": defn["cost_tier"],
        "match_confidence": min(best_score / 3.0, 1.0),
    }


def compute_value_score(leverage_score: float, cost_tier: str) -> float:
    multiplier = COST_MULTIPLIERS.get(cost_tier, 1.0)
    return round(leverage_score / multiplier, 2)


def get_specialization_boost(agent_profile: str, category: str) -> float:
    spec = AGENT_SPECIALIZATIONS.get(agent_profile, AGENT_SPECIALIZATIONS["generalist"])
    try:
        cat = TaskCategory(category)
    except ValueError:
        return 0.0

    if cat in spec["primary"]:
        return spec["confidence_boost"]
    if cat in spec["secondary"]:
        return spec["secondary_boost"]
    return 0.0


def list_categories(tier: Optional[str] = None) -> list:
    results = []
    for category, defn in TASK_DEFINITIONS.items():
        if category == TaskCategory.UNCATEGORIZED:
            continue
        if tier and defn["tier"].value != tier:
            continue
        results.append({
            "category": category.value,
            "rank": defn["rank"],
            "tier": defn["tier"].value,
            "label": defn["label"],
            "description": defn["description"],
            "leverage_score": defn["leverage_score"],
            "cost_tier": defn["cost_tier"],
            "value_score": compute_value_score(defn["leverage_score"], defn["cost_tier"]),
        })
    results.sort(key=lambda x: x["rank"])
    return results
