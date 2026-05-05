"""
Unit tests for polymarket_bot.monitoring.logging.

Tests:
  - setup_logging() returns BoundLogger
  - Logger emits JSON lines
  - Different log levels are respected
"""

import pytest
import json
import sys
from io import StringIO
from polymarket_bot.monitoring.logging import setup_logging, get_logger
from unittest.mock import patch


class DummyMonitoringConfig:
    """Stand-in for MonitoringConfig Pydantic model."""
    log_level = "DEBUG"
    log_file = "~/.trading_bot/test-logs/bot-%Y-%m-%d.log"
    log_rotation = "daily"
    log_retention_days = 7
    log_json = True


class TestLoggingSetup:
    """Test logger initialization."""

    def test_setup_returns_logger(self):
        cfg = DummyMonitoringConfig()
        logger = setup_logging(cfg)
        assert logger is not None
        # Logger should be bound to trading_bot
        assert logger.name == "trading_bot"

    def test_logger_has_info_method(self):
        cfg = DummyMonitoringConfig()
        logger = setup_logging(cfg)
        # Should have standard logging methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_get_logger_returns_same_instance(self):
        # After setup, get_logger() returns cached logger
        cfg = DummyMonitoringConfig()
        setup_logging(cfg)
        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2


class TestLogOutput:
    """Test that log messages are properly formatted as JSON."""

    def test_info_message_json_serializable(self, capsys):
        cfg = DummyMonitoringConfig()
        logger = setup_logging(cfg)
        logger.info("test message", key="value", num=42)

        captured = capsys.readouterr()
        # stderr output (our logs go to stderr)
        line = captured.err.strip().split("\n")[-1]
        parsed = json.loads(line)
        assert parsed["event"] == "test message"
        assert parsed["key"] == "value"
        assert parsed["num"] == 42

    def test_debug_message_included_when_debug(self, capsys):
        cfg = DummyMonitoringConfig()
        cfg.log_level = "DEBUG"
        logger = setup_logging(cfg)
        logger.debug("debug msg", detail="x")

        captured = capsys.readouterr()
        assert "debug msg" in captured.err

    def test_debug_message_filtered_when_info(self, capsys):
        cfg = DummyMonitoringConfig()
        cfg.log_level = "INFO"
        logger = setup_logging(cfg)
        logger.debug("debug msg hidden")

        captured = capsys.readouterr()
        # Debug should not appear in output at INFO level
        assert "debug msg hidden" not in captured.err

    def test_exception_logging_includes_traceback(self, capsys):
        cfg = DummyMonitoringConfig()
        logger = setup_logging(cfg)
        try:
            raise ValueError("test error")
        except ValueError:
            logger.error("exception occurred", exc_info=True)

        captured = capsys.readouterr()
        assert "exception occurred" in captured.err
        assert "Traceback" in captured.err  # JSON includes exc_info

    def test_structured_context_included(self, capsys):
        cfg = DummyMonitoringConfig()
        logger = setup_logging(cfg)
        logger.info("trade_event", asset="BTC", window="5m", price=50000.0)

        captured = capsys.readouterr()
        line = captured.err.strip().splitlines()[-1]
        parsed = json.loads(line)
        assert parsed["asset"] == "BTC"
        assert parsed["window"] == "5m"
        assert parsed["price"] == 50000.0


class TestLogLevels:
    """Test log level filtering."""

    @pytest.mark.parametrize("level_name,should_log", [
        ("DEBUG", True),
        ("INFO", True),
        ("WARNING", True),
        ("ERROR", True),
        ("CRITICAL", True),
    ])
    def test_all_levels_enabled(self, capsys, level_name, should_log):
        cfg = DummyMonitoringConfig()
        cfg.log_level = "DEBUG"  # enable all
        logger = setup_logging(cfg)
        log_fn = getattr(logger, level_name.lower())
        log_fn(f"test {level_name}")

        captured = capsys.readouterr()
        assert f"test {level_name}" in captured.err

    def test_info_level_filters_debug(self, capsys):
        cfg = DummyMonitoringConfig()
        cfg.log_level = "INFO"
        logger = setup_logging(cfg)
        logger.debug("debug hidden")
        logger.info("info shown")

        captured = capsys.readouterr()
        assert "debug hidden" not in captured.err
        assert "info shown" in captured.err


class TestLoggerContext:
    """Test bound context (logger = logger.bind(...))."""

    def test_bound_logger_includes_context(self, capsys):
        cfg = DummyMonitoringConfig()
        base = setup_logging(cfg)
        bound = base.bind(component="matrix", step="update")
        bound.info("matrix updated", state=42)

        captured = capsys.readouterr()
        line = captured.err.strip().splitlines()[-1]
        parsed = json.loads(line)
        assert parsed["component"] == "matrix"
        assert parsed["step"] == "update"
        assert parsed["state"] == 42
