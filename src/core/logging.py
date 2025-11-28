"""Structured logging configuration for the MIRT AI system.

This module provides JSON-formatted logging suitable for production environments
and log aggregation systems (ELK, CloudWatch, etc.).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def __init__(
        self,
        *,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_logger: bool = True,
        include_path: bool = False,
        extra_fields: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_logger = include_logger
        self.include_path = include_path
        self.extra_fields = extra_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        log_data: dict[str, Any] = {}

        # Standard fields
        if self.include_timestamp:
            log_data["timestamp"] = datetime.now(UTC).isoformat()

        if self.include_level:
            log_data["level"] = record.levelname

        if self.include_logger:
            log_data["logger"] = record.name

        # Message
        log_data["message"] = record.getMessage()

        # Source location
        if self.include_path:
            log_data["path"] = f"{record.pathname}:{record.lineno}"
            log_data["function"] = record.funcName

        # Exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Extra fields from record
        for key in ["session_id", "user_id", "request_id", "duration_ms", "status_code"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        # Static extra fields
        log_data.update(self.extra_fields)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class PrettyFormatter(logging.Formatter):
    """Human-readable formatter for development/debugging."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with colors and structured info."""
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        level = f"{color}{record.levelname:8}{reset}"
        logger_name = record.name[:20].ljust(20)
        message = record.getMessage()

        # Build output
        output = f"{timestamp} | {level} | {logger_name} | {message}"

        # Add exception if present
        if record.exc_info:
            output += f"\n{self.formatException(record.exc_info)}"

        return output


def setup_logging(
    *,
    level: str = "INFO",
    json_format: bool = False,
    include_path: bool = False,
    service_name: str = "mirt-ai",
) -> None:
    """Configure logging for the application.

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON format (True) or pretty format (False)
        include_path: Include source file path in logs
        service_name: Service name to include in JSON logs
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))

    # Set formatter
    if json_format:
        formatter = JSONFormatter(
            include_path=include_path,
            extra_fields={"service": service_name},
        )
    else:
        formatter = PrettyFormatter()

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("supabase").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Usage:
        logger = get_logger(__name__)
        logger.info("Processing request", extra={"session_id": "abc123"})
    """
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding context to log records.

    Usage:
        with LogContext(session_id="abc123", user_id="user456"):
            logger.info("Processing message")  # Will include session_id and user_id
    """

    def __init__(self, **kwargs: Any):
        self.context = kwargs
        self._old_factory = None

    def __enter__(self) -> LogContext:
        self._old_factory = logging.getLogRecordFactory()

        context = self.context

        def record_factory(*args, **kwargs):
            record = self._old_factory(*args, **kwargs)
            for key, value in context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        logging.setLogRecordFactory(self._old_factory)
