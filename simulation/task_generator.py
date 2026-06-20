import uuid
import random

TASK_TEMPLATES = {
    "code_generation": [
        "Implement authentication middleware for the API gateway",
        "Refactor database query layer to use async connection pooling",
        "Build a REST endpoint for user profile management",
        "Debug race condition in the payment processing module",
        "Develop a CLI tool for automated database migrations",
    ],
    "complex_reasoning": [
        "Analyze tradeoffs between microservices vs monolith for our scale",
        "Evaluate caching strategy options and recommend architecture",
        "Design a fault-tolerant system for processing financial transactions",
        "Plan the migration strategy from PostgreSQL to distributed database",
        "Reason through capacity planning for 10x traffic growth",
    ],
    "data_analysis": [
        "Analyze server performance metrics and identify bottlenecks",
        "Build a dashboard showing customer conversion funnel trends",
        "Generate a report on API latency percentiles by endpoint",
        "Create data visualization of monthly revenue forecast model",
        "Benchmark database query performance across index strategies",
    ],
    "research_synthesis": [
        "Research and summarize best practices for zero-trust security",
        "Synthesize literature on LLM fine-tuning approaches for code",
        "Compare findings across database scaling research papers",
        "Survey available open-source tools for observability and monitoring",
        "Review and summarize recent advances in vector embedding models",
    ],
    "workflow_automation": [
        "Automate the CI/CD pipeline for staging deployments",
        "Build a webhook integration for Slack notification triggers",
        "Create an ETL pipeline for daily data warehouse refresh",
        "Schedule recurring batch processing for report generation",
        "Set up automated dependency update workflow with approval gates",
    ],
    "customer_support": [
        "Build an FAQ chatbot for handling common customer inquiries",
        "Create ticket routing rules based on customer tier and issue type",
        "Generate templated responses for top 20 support categories",
        "Implement customer sentiment analysis on support conversations",
        "Design escalation workflow for unresolved support tickets",
    ],
    "content_generation": [
        "Write a technical blog post about our new API features",
        "Generate marketing copy for the product launch landing page",
        "Create social media content calendar for developer outreach",
        "Rewrite the onboarding email sequence for better engagement",
        "Draft a press release for the platform availability announcement",
    ],
    "translation": [
        "Translate the user interface strings to Spanish and French",
        "Localize the documentation for the Japanese market",
        "Create multilingual versions of the API error messages",
        "Translate marketing materials for the German language launch",
        "Build internationalization support for date and currency formats",
    ],
    "search_rag": [
        "Build a semantic search index over internal documentation",
        "Implement RAG pipeline for knowledge base question answering",
        "Create vector embeddings for product catalog search",
        "Design retrieval pipeline for context-aware code suggestions",
        "Set up hybrid search combining keyword and semantic matching",
    ],
    "task_extraction": [
        "Extract action items from the quarterly planning document",
        "Parse and structure customer feedback forms into categories",
        "Build entity extraction pipeline for contract analysis",
        "Classify incoming emails by intent and urgency level",
        "Tag and annotate unstructured log entries with error categories",
    ],
    "meeting_summarization": [
        "Summarize the engineering standup and extract action items",
        "Generate meeting minutes from the product review transcript",
        "Create a summary of key decisions from the board meeting notes",
        "Extract follow-up tasks from the sprint retrospective",
        "Summarize the all-hands meeting highlights and announcements",
    ],
    "email_triage": [
        "Draft a reply to the partnership inquiry email",
        "Triage the support inbox and prioritize by urgency",
        "Create email templates for common vendor communication flows",
        "Build priority scoring rules for incoming customer emails",
        "Generate weekly email digest of project status updates",
    ],
    "project_planning": [
        "Create a project plan for the Q3 platform migration",
        "Build a sprint roadmap with milestone dependencies",
        "Plan resource allocation for the next two development sprints",
        "Design a Gantt timeline for the product launch deliverables",
        "Break down the epic into estimable user stories for backlog",
    ],
    "data_cleaning": [
        "Clean and deduplicate the customer contact database",
        "Transform CSV exports into normalized JSON schema format",
        "Validate and sanitize user-submitted form data entries",
        "Convert legacy XML records to the new data model format",
        "Normalize inconsistent date formats across the dataset",
    ],
    "document_comparison": [
        "Compare the updated privacy policy against the previous version",
        "Review contract changes and highlight compliance differences",
        "Diff the API specification between v2 and v3 releases",
        "Audit the security policy document for regulatory gaps",
        "Generate a changelog from document version differences",
    ],
    "image_generation": [
        "Generate hero banner images for the product marketing campaign",
        "Create illustration visuals for the developer blog posts",
        "Design thumbnail graphics for the video content series",
        "Generate branded social media image templates",
        "Create visual diagrams for the system architecture documentation",
    ],
    "video_scripting": [
        "Write a video script for the product demo walkthrough",
        "Create storyboard and narration for the onboarding tutorial",
        "Draft a script for the developer conference presentation",
        "Generate voiceover text for the feature announcement video",
        "Write scene descriptions for the customer testimonial clips",
    ],
    "api_documentation": [
        "Generate API documentation for the new payment endpoints",
        "Write an OpenAPI spec for the user management service",
        "Create a developer guide for the webhook integration API",
        "Document the authentication flow with code examples",
        "Update the API reference with new query parameter descriptions",
    ],
    "unit_test_generation": [
        "Generate unit tests for the authentication middleware",
        "Write integration test suite for the payment processing flow",
        "Create pytest fixtures for the database interaction layer",
        "Generate test cases for edge conditions in the validation module",
        "Build mock-based tests for external API client coverage",
    ],
    "product_mockups": [
        "Create a wireframe mockup for the new dashboard layout",
        "Design a UI prototype for the mobile settings screen",
        "Build a component library mockup for the design system",
        "Generate layout options for the analytics page redesign",
        "Create a Figma prototype for the user onboarding flow",
    ],
}

SOURCES = ["github", "slack", "manual", "recurring", "email", "api", "webhook"]

ALL_OBJECTIVES = []
OBJECTIVE_CATEGORIES = {}
for cat, objectives in TASK_TEMPLATES.items():
    for obj in objectives:
        ALL_OBJECTIVES.append(obj)
        OBJECTIVE_CATEGORIES[obj] = cat


def gen(category: str = None):
    if category and category in TASK_TEMPLATES:
        objective = random.choice(TASK_TEMPLATES[category])
    else:
        objective = random.choice(ALL_OBJECTIVES)

    return {
        "id": str(uuid.uuid4()),
        "objective": objective,
        "source": random.choice(SOURCES),
        "inputs": {},
    }
