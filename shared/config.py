import os

ENV = os.getenv("VERIXIO_ENV", "development")

_PROFILES = {
    "development": {
        "MAX_RETRIES": 3,
        "RETRY_BACKOFF": 0.3,
        "DEFAULT_TIMEOUT": 10.0,
        "PIPELINE_TIMEOUT": 15.0,
        "QUICK_TIMEOUT": 5.0,
        "OPENROUTER_TIMEOUT": 120.0,
        "RATE_LIMIT_MAX_REQUESTS": 100,
        "RATE_LIMIT_WINDOW_SECONDS": 60,
        "CORS_ORIGINS": "http://localhost:3000",
        "LOG_LEVEL": "DEBUG",
        "DB_BACKEND": "sqlite",
        "MARKUP_MULTIPLIER": 3.0,
        "MINIMUM_QUOTE_USD": 5.0,
    },
    "staging": {
        "MAX_RETRIES": 3,
        "RETRY_BACKOFF": 0.5,
        "DEFAULT_TIMEOUT": 15.0,
        "PIPELINE_TIMEOUT": 20.0,
        "QUICK_TIMEOUT": 5.0,
        "OPENROUTER_TIMEOUT": 120.0,
        "RATE_LIMIT_MAX_REQUESTS": 200,
        "RATE_LIMIT_WINDOW_SECONDS": 60,
        "CORS_ORIGINS": "https://staging.agentn9er.com",
        "LOG_LEVEL": "INFO",
        "DB_BACKEND": "postgres",
        "MARKUP_MULTIPLIER": 3.0,
        "MINIMUM_QUOTE_USD": 5.0,
    },
    "production": {
        "MAX_RETRIES": 5,
        "RETRY_BACKOFF": 1.0,
        "DEFAULT_TIMEOUT": 15.0,
        "PIPELINE_TIMEOUT": 30.0,
        "QUICK_TIMEOUT": 5.0,
        "OPENROUTER_TIMEOUT": 180.0,
        "RATE_LIMIT_MAX_REQUESTS": 500,
        "RATE_LIMIT_WINDOW_SECONDS": 60,
        "CORS_ORIGINS": "https://agentn9er.com",
        "LOG_LEVEL": "WARNING",
        "DB_BACKEND": "postgres",
        "MARKUP_MULTIPLIER": 3.0,
        "MINIMUM_QUOTE_USD": 5.0,
    },
}


def _get(key: str, cast=str):
    env_val = os.getenv(key)
    if env_val is not None:
        return cast(env_val)
    profile = _PROFILES.get(ENV, _PROFILES["development"])
    return cast(profile.get(key, _PROFILES["development"][key]))


MAX_RETRIES = _get("MAX_RETRIES", int)
RETRY_BACKOFF = _get("RETRY_BACKOFF", float)

DEFAULT_TIMEOUT = _get("DEFAULT_TIMEOUT", float)
PIPELINE_TIMEOUT = _get("PIPELINE_TIMEOUT", float)
QUICK_TIMEOUT = _get("QUICK_TIMEOUT", float)

RATE_LIMIT_MAX_REQUESTS = _get("RATE_LIMIT_MAX_REQUESTS", int)
RATE_LIMIT_WINDOW_SECONDS = _get("RATE_LIMIT_WINDOW_SECONDS", int)

CORS_ORIGINS = _get("CORS_ORIGINS").split(",")
LOG_LEVEL = _get("LOG_LEVEL")
DB_BACKEND = _get("DB_BACKEND")
