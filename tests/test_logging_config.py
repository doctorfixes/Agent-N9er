"""Tests for shared logging configuration and Sentry integration."""

import json
import logging
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.logging_config import JSONFormatter, setup_sentry, setup_logging


class TestJSONFormatter:
    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "hello world"
        assert "timestamp" in data

    def test_request_id_included(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="with request id", args=(), exc_info=None,
        )
        record.request_id = "req-123"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-123"

    def test_service_field(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        record.service = "orchestrator"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["service"] == "orchestrator"

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "ValueError" in data["exception"]
        assert "boom" in data["exception"]


class TestSetupSentry:
    @patch.dict(os.environ, {"SENTRY_DSN": ""})
    def test_no_dsn_skips(self):
        import shared.logging_config as lc
        lc.SENTRY_DSN = ""
        setup_sentry("test-service")

    @patch.dict(os.environ, {"SENTRY_DSN": "https://fake@sentry.io/123"})
    def test_missing_sdk_warns(self, caplog):
        import shared.logging_config as lc
        lc.SENTRY_DSN = "https://fake@sentry.io/123"
        with patch.dict(sys.modules, {"sentry_sdk": None}):
            with patch("builtins.__import__", side_effect=ImportError("no sentry")):
                setup_sentry("test-service")


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("test-unit")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test-unit"

    @patch.dict(os.environ, {"VERIXIO_ENV": "development"})
    def test_development_uses_plain_formatter(self):
        import shared.logging_config as lc
        import shared.config
        import importlib
        importlib.reload(shared.config)
        importlib.reload(lc)
        logger = lc.setup_logging("test-dev")
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)

    @patch.dict(os.environ, {"VERIXIO_ENV": "production"})
    def test_production_uses_json_formatter(self):
        import shared.logging_config as lc
        import shared.config
        import importlib
        importlib.reload(shared.config)
        importlib.reload(lc)
        logger = lc.setup_logging("test-prod")
        root = logging.getLogger()
        assert type(root.handlers[0].formatter).__name__ == "JSONFormatter"
