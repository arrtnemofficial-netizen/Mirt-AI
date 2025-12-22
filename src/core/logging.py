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


# Event titles mapping for emoji-formatted log messages
# Based on data/prompts/system/vision.md LOG_TITLES
LOG_EVENT_TITLES: dict[str, str] = {
    "api_v1_payload_received": "📩 API: payload отримано",
    "api_v1_payload_parsed": "🧾 API: payload розібрано",
    "api_v1_task_scheduled": "🛰️ API: задача запланована",
    "api_v1_task_timeout": "⏱️ API: timeout (45c)",
    "manychat_task_scheduled": "🛰️ ManyChat: задача запланована",
    "manychat_message_accepted": "📬 ManyChat: прийнято (202)",
    "manychat_process_start": "🔥 ManyChat: старт обробки",
    "manychat_rate_limited": "⏳ ManyChat: rate limit",
    "manychat_restart_command": "🔄 ManyChat: /restart",
    "manychat_image_attached": "🖼️ ManyChat: додано фото",
    "manychat_subscriber_username": "🧾 ManyChat: username знайдено",
    "manychat_subscriber_name": "👤 ManyChat: ім'я знайдено",
    "manychat_debounce_superseded": "🧯 Debounce: запит замінено новішим",
    "manychat_debounce_aggregated": "🧩 Debounce: зібрано повідомлення",
    "manychat_fallback_triggered": "🆘 Fallback: спрацював",
    "manychat_including_images": "🖼️ ManyChat: додаю фото товарів",
    "manychat_push_attempt": "📤 ManyChat: push спроба",
    "manychat_push_ok": "✅ ManyChat: push успішний",
    "manychat_push_rejected": "⛔ ManyChat: push відхилено",
    "manychat_push_failed": "❌ ManyChat: push не вдався",
    "manychat_processing_error": "💥 ManyChat: помилка обробки",
    "manychat_process_done": "🏁 ManyChat: обробку завершено",
}


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    level: str | None = None,
    **kwargs: Any,
) -> None:
    """Structured event logging helper with emoji formatting.
    
    Formats log messages with emoji titles from LOG_EVENT_TITLES and
    structured data for better readability.
    
    Special formatting for 'manychat_process_done':
        🏁 ManyChat: обробку завершено — {latency_ms}ms | {current_state} | {intent} | msgs={messages_count} | prod={products_count}
    
    Args:
        logger: Logger instance to use
        event: Event name (key in LOG_EVENT_TITLES)
        level: Log level (debug, info, warning, error, critical)
        **kwargs: Additional context fields (latency_ms, current_state, intent, etc.)
    """
    lvl = (level or "info").lower()
    log_fn = getattr(logger, lvl, logger.info)
    
    # Get emoji title for the event
    title = LOG_EVENT_TITLES.get(event, event)
    
    # Special formatting for manychat_process_done
    if event == "manychat_process_done":
        latency_ms = kwargs.get("latency_ms")
        current_state = kwargs.get("current_state")
        intent = kwargs.get("intent")
        messages_count = kwargs.get("messages_count", 0)
        products_count = kwargs.get("products_count", 0)
        
        # Build structured message
        parts = [title]
        if latency_ms is not None:
            parts.append(f"— {latency_ms}ms")
        if current_state:
            parts.append(f"| {current_state}")
        if intent:
            parts.append(f"| {intent}")
        parts.append(f"| msgs={messages_count}")
        parts.append(f"| prod={products_count}")
        
        message = " ".join(parts)
    else:
        # For other events, use the title as-is
        message = title
    
    # Log with structured data in extra
    log_fn(message, extra={"event": event, **kwargs})


def safe_preview(value: Any, max_len: int = 120) -> str:
    """Return a safe string preview of value."""
    if value is None:
        return ""
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def classify_root_cause(
    error: Any,
    *,
    current_state: str | None = None,
    intent: str | None = None,
    channel: str | None = None,
    status_code: int | None = None,
) -> str:
    """Classify error root cause for structured logging."""
    msg = str(error or "").lower()
    state = (current_state or "").upper()
    intent_norm = (intent or "").upper()
    channel_norm = (channel or "").lower()

    if status_code is not None:
        if status_code == 400 and ("field" in msg and "not found" in msg):
            return "MANYCHAT_FIELD_NOT_FOUND"
        if 400 <= status_code < 500:
            return f"MANYCHAT_REJECTED_{status_code}"
        if status_code >= 500:
            return f"MANYCHAT_UPSTREAM_{status_code}"

    if "agentresponse" in msg and "no attribute" in msg:
        return "CONTRACT_MISMATCH"
    if "timeout" in msg or "timed out" in msg:
        return "LLM_TIMEOUT"
    if "rate limit" in msg or "429" in msg:
        return "LLM_RATE_LIMIT"
    if "vision" in msg or "image" in msg or "cdn" in msg:
        return "VISION_ERROR"
    if "supabase" in msg or "postgres" in msg or "psycopg" in msg:
        return "STORAGE_ERROR"
    if "manychat" in msg:
        return "MANYCHAT_ERROR"

    if intent_norm == "PHOTO_IDENT" or "VISION" in state:
        return "VISION_FLOW_ERROR"
    if state.startswith("STATE_"):
        return f"STATE_FLOW_ERROR:{state}"
    if channel_norm:
        return f"CHANNEL_ERROR:{channel_norm}"
    return "UNKNOWN"


def log_with_root_cause(
    logger: logging.Logger,
    level: str,
    message: str,
    *,
    root_cause: str | None = None,
    error: Exception | None = None,
    auto_classify: bool = True,
    **context: Any,
) -> None:
    """Log with root cause in [ROOT_CAUSE: ...] brackets for AI share detection.

    This function ensures all production logs have structured root cause information
    that can be easily parsed by monitoring systems and AI share detection.

    Args:
        logger: Logger instance to use
        level: Log level (debug, info, warning, error, critical)
        message: Base log message
        root_cause: Explicit root cause (if None, will auto-classify from error)
        error: Exception object (used for auto-classification if root_cause is None)
        auto_classify: If True, automatically classify root cause from error
        **context: Additional context fields (session_id, user_id, etc.)

    Example:
        ```python
        logger = get_logger(__name__)
        try:
            result = await api_call()
        except Exception as e:
            log_with_root_cause(
                logger,
                "error",
                "Failed to call API",
                error=e,
                status_code=500,
                session_id="abc123",
            )
        # Output: "Failed to call API [ROOT_CAUSE: MANYCHAT_UPSTREAM_500]"
        ```
    """
    # Normalize level
    level = level.upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = "INFO"

    # Auto-classify root cause if not provided
    if root_cause is None and auto_classify and error is not None:
        root_cause = classify_root_cause(
            error,
            status_code=context.get("status_code"),
            channel=context.get("channel"),
            current_state=context.get("current_state"),
            intent=context.get("intent"),
        )

    # Build message with root cause in brackets
    if root_cause:
        message = f"{message} [ROOT_CAUSE: {root_cause}]"

    # Prepare extra context
    extra = context.copy()
    if root_cause:
        extra["root_cause"] = root_cause
    if error:
        extra["error_type"] = type(error).__name__
        extra["error_message"] = str(error)

    # Get log function
    log_fn = getattr(logger, level.lower(), logger.info)

    # Log with exception info if error provided
    if error:
        log_fn(message, extra=extra, exc_info=error)
    else:
        log_fn(message, extra=extra)


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
