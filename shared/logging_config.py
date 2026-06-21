import json
import logging
import sys
import os
from datetime import datetime, timezone

from shared.config import LOG_LEVEL, ENV

SENTRY_DSN = os.getenv("SENTRY_DSN", "")


class JSONFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", None),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_sentry(service_name: str):
    if not SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=ENV,
            traces_sample_rate=0.2 if ENV == "production" else 1.0,
            profiles_sample_rate=0.1,
            integrations=[FastApiIntegration(), HttpxIntegration()],
            release=f"agent-n9er-{service_name}",
        )
    except ImportError:
        logging.getLogger(service_name).warning("sentry-sdk not installed — error tracking disabled")


def setup_logging(service_name: str):
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)

    if ENV == "development":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
    else:
        handler.setFormatter(JSONFormatter())

    root_logger.addHandler(handler)

    setup_sentry(service_name)

    logger = logging.getLogger(service_name)
    logger.info("Logging initialized for %s (env=%s, level=%s)", service_name, ENV, LOG_LEVEL)
    return logger
