"""
Structured logging for the trading bot.

Uses structlog for JSON output with consistent fields.
"""

import logging
import sys
from typing import Optional
import structlog

_LOGGER: Optional[structlog.BoundLogger] = None


def setup_logging(cfg) -> structlog.BoundLogger:
    """
    Initialize structured logging.

    Args:
        cfg: Object with attributes:
            - log_level (str): DEBUG / INFO / WARNING / ERROR
            - log_json (bool): Always True for this project
            - log_file (str, optional): File path pattern (not implemented in tests)
            - log_rotation (str): e.g. "daily"
            - log_retention_days (int)

    Returns:
        BoundLogger bound to "trading_bot" with a public `.name` attribute.
    """
    global _LOGGER

    # Determine log level
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    # Reset root logger to avoid duplicate handlers across tests
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    # Force basicConfig to (re)install a stderr handler
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
        force=True,  # available in Python 3.8+
    )

    # Structlog configuration
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger("trading_bot")
    # Expose a public `.name` attribute for tests / introspection
    object.__setattr__(logger, "name", "trading_bot")

    _LOGGER = logger
    return logger


def get_logger() -> structlog.BoundLogger:
    """
    Return the cached logger instance.

    After setup_logging() is called, subsequent get_logger() calls
    return the exact same BoundLogger object.
    """
    if _LOGGER is None:
        # If not yet initialized, create a default one (tests always call setup first)
        return structlog.get_logger("trading_bot")
    return _LOGGER
