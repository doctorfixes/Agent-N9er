import os

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "0.3"))

DEFAULT_TIMEOUT = float(os.getenv("DEFAULT_TIMEOUT", "10.0"))
PIPELINE_TIMEOUT = float(os.getenv("PIPELINE_TIMEOUT", "15.0"))
QUICK_TIMEOUT = float(os.getenv("QUICK_TIMEOUT", "5.0"))

RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
