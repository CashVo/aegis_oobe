# tests/test_observer/test_logging.py
# Unit tests for the structured logging module.
"""
Tests cover:
- Logger creation with bound context
- FallbackLogger stderr output
- configure_logging doesn't raise
"""

import sys
import json
import pytest
from io import StringIO
from unittest.mock import patch

from aegis.observer.logging import (
    configure_logging,
    get_logger,
    FallbackLogger,
)


class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_logging_default(self):
        """Test that configure_logging runs without errors."""
        # Should not raise
        configure_logging(log_level="DEBUG", json_output=True)

    def test_configure_logging_console_mode(self):
        """Test console (non-JSON) mode configuration."""
        configure_logging(log_level="INFO", json_output=False)


class TestGetLogger:
    """Tests for structured logger creation."""

    def test_get_logger_basic(self):
        """Test basic logger creation."""
        configure_logging(log_level="DEBUG", json_output=True)
        logger = get_logger()
        assert logger is not None

    def test_get_logger_with_context(self):
        """Test logger creation with bound context fields."""
        configure_logging(log_level="DEBUG", json_output=True)
        logger = get_logger(
            agent_id="forge",
            tenant_id="tenant-123",
            user_id="user-456",
        )
        assert logger is not None
        # The logger should have bound context (structlog internals)


class TestFallbackLogger:
    """Tests for FallbackLogger (RT-3 stderr fallback)."""

    def test_fallback_logger_output(self):
        """Test that FallbackLogger writes JSON to stderr."""
        logger = FallbackLogger(agent_id="test_agent")

        captured = StringIO()
        with patch("sys.stderr", captured):
            logger.info("Test message", extra_key="extra_value")

        output = captured.getvalue().strip()
        parsed = json.loads(output)

        assert parsed["level"] == "info"
        assert parsed["agent_id"] == "test_agent"
        assert parsed["event"] == "Test message"
        assert parsed["extra_key"] == "extra_value"
        assert "timestamp" in parsed

    def test_fallback_logger_all_levels(self):
        """Test all log levels emit to stderr."""
        logger = FallbackLogger(agent_id="multi_level")

        levels = ["debug", "info", "warning", "error", "critical"]
        captured = StringIO()

        with patch("sys.stderr", captured):
            for level in levels:
                getattr(logger, level)(f"{level} message")

        lines = captured.getvalue().strip().split("\n")
        assert len(lines) == 5

        for i, level in enumerate(levels):
            parsed = json.loads(lines[i])
            assert parsed["level"] == level
            assert parsed["event"] == f"{level} message"
