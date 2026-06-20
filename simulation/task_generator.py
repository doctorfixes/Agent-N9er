import uuid
import random

OBJECTIVES = [
    "Review pull request for auth module",
    "Deploy staging environment",
    "Fix urgent login bug on production",
    "Write unit tests for payment service",
    "Update API documentation",
    "Analyze server performance metrics",
    "Refactor database query optimization",
    "Create user onboarding flow",
    "Investigate critical memory leak",
    "Build CSV export feature",
    "Set up monitoring dashboard",
    "Migrate legacy endpoints to v2 API",
    "Run security audit on dependencies",
    "Fix CORS configuration for mobile app",
    "Implement rate limiting middleware",
]

SOURCES = ["github", "slack", "manual", "recurring", "email"]


def gen():
    return {
        "id": str(uuid.uuid4()),
        "objective": random.choice(OBJECTIVES),
        "source": random.choice(SOURCES),
        "inputs": {},
    }
