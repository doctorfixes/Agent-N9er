"""Tests for shared/logging_config.py — JSONFormatter and setup_logging."""

import json
import logging
import sys
from unittest.mock import patch

import pytest


class TestJSONFormatter:
    def test_format_basic_record(self):
        from shared.logging_config import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "hello world"
        assert "timestamp" in data
        assert data["service"] is None

    def test_format_includes_service_attribute(self):
        from shared.logging_config import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="warning message",
            args=(),
            exc_info=None,
        )
        record.service = "my-service"
        output = formatter.format(record)
        data = json.loads(output)

        assert data["service"] == "my-service"

    def test_format_with_exception_info(self):
        from shared.logging_config import JSONFormatter

        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="something failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "boom" in data["exception"]

    def test_format_without_exception_info(self):
        from shared.logging_config import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg="debug message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" not in data


class TestSetupLogging:
    def test_development_env_uses_standard_formatter(self, monkeypatch):
        monkeypatch.setattr("shared.logging_config.ENV", "development")
        monkeypatch.setattr("shared.logging_config.LOG_LEVEL", "DEBUG")

        from shared.logging_config import JSONFormatter, setup_logging

        logger = setup_logging("test-dev-service")
        assert logger.name == "test-dev-service"

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        handler = root.handlers[-1]
        assert not isinstance(handler.formatter, JSONFormatter)

    def test_production_env_uses_json_formatter(self, monkeypatch):
        monkeypatch.setattr("shared.logging_config.ENV", "production")
        monkeypatch.setattr("shared.logging_config.LOG_LEVEL", "WARNING")

        from shared.logging_config import JSONFormatter, setup_logging

        logger = setup_logging("test-prod-service")
        assert logger.name == "test-prod-service"

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        handler = root.handlers[-1]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_setup_logging_sets_correct_level(self, monkeypatch):
        monkeypatch.setattr("shared.logging_config.ENV", "development")
        monkeypatch.setattr("shared.logging_config.LOG_LEVEL", "ERROR")

        from shared.logging_config import setup_logging

        setup_logging("test-level-service")
        root = logging.getLogger()
        assert root.level == logging.ERROR

    def test_setup_logging_removes_previous_handlers(self, monkeypatch):
        monkeypatch.setattr("shared.logging_config.ENV", "development")
        monkeypatch.setattr("shared.logging_config.LOG_LEVEL", "INFO")

        from shared.logging_config import setup_logging

        root = logging.getLogger()
        dummy_handler = logging.StreamHandler()
        root.addHandler(dummy_handler)

        setup_logging("test-clean-service")
        # The dummy handler should have been removed; only the new one remains
        assert dummy_handler not in root.handlers
