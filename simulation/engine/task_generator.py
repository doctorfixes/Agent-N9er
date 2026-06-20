import uuid
import random

OBJECTIVES = [
    "Review pull request for auth module",
    "Deploy staging environment",
    "Fix urgent login bug on production",
    "Write unit tests for payment service",
    "Update API documentation",
]


def gen():
    return {
        "id": str(uuid.uuid4()),
        "objective": random.choice(OBJECTIVES),
        "source": "simulation",
        "inputs": {},
    }
