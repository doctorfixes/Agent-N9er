import json
import logging
import sys
import os
from datetime import datetime, timezone

from shared.config import LOG_LEVEL, ENV


class JSONFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", None),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


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

    logger = logging.getLogger(service_name)
    logger.info("Logging initialized for %s (env=%s, level=%s)", service_name, ENV, LOG_LEVEL)
    return logger
