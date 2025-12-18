"""Structured logging configuration for the MIRT AI system.

This module provides JSON-formatted logging suitable for production environments
and log aggregation systems (ELK, CloudWatch, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any


def safe_preview(value: Any, limit: int = 160) -> str:
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def classify_root_cause(
    error: Any,
    *,
    current_state: str | None = None,
    intent: str | None = None,
    channel: str | None = None,
    status_code: int | None = None,
) -> str:
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


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    titles: dict[str, str] = {
        "api_v1_payload_received": "📩 API: payload отримано",
        "api_v1_payload_parsed": "🧾 API: payload розібрано",
        "api_v1_task_scheduled": "🛰️ API: задача запланована",
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

    fields["event"] = event

    if "badge" not in fields:
        if event.startswith("manychat_"):
            fields["badge"] = "MANYCHAT"
        elif event.startswith("api_v1_") or event.startswith("api_"):
            fields["badge"] = "API"
        elif event.startswith("agent_"):
            fields["badge"] = "AGENT"
        elif event.startswith("tool_"):
            fields["badge"] = "TOOL"

    if "stage" not in fields:
        if "debounce" in event:
            fields["stage"] = "DEBOUNCE"
        elif "push" in event:
            fields["stage"] = "PUSH"
        elif event.endswith("_done"):
            fields["stage"] = "DONE"
        elif "error" in event or "fallback" in event or "rejected" in event:
            fields["stage"] = "ERROR"
        else:
            fields["stage"] = "INGEST"

    message = titles.get(event, event)
    root_cause = str(fields.get("root_cause") or "").strip()
    if root_cause and ("error" in event or "fallback" in event or "rejected" in event):
        message = f"{message} — {root_cause}"

    if event == "manychat_process_done":
        latency_ms = fields.get("latency_ms")
        st = str(fields.get("current_state") or "").strip()
        it = str(fields.get("intent") or "").strip()
        msgs = fields.get("messages_count")
        prods = fields.get("products_count")
        bits: list[str] = []
        if isinstance(latency_ms, (int, float)):
            bits.append(f"{int(latency_ms)}ms")
        if st:
            bits.append(st)
        if it:
            bits.append(it)
        if isinstance(msgs, int):
            bits.append(f"msgs={msgs}")
        if isinstance(prods, int):
            bits.append(f"prod={prods}")
        if bits:
            message = f"{message} — " + " | ".join(bits)

    method = getattr(logger, level, None)
    if callable(method):
        method(message, extra=fields)
        return
    logger.info(message, extra=fields)


def _get_build_info() -> dict[str, str]:
    sha = (
        os.environ.get("GIT_SHA")
        or os.environ.get("COMMIT_SHA")
        or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or os.environ.get("GITHUB_SHA")
        or "unknown"
    )
    build_id = (
        os.environ.get("BUILD_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RENDER_INSTANCE_ID")
        or os.environ.get("DYNO")
        or os.environ.get("HOSTNAME")
        or "unknown"
    )
    return {"git_sha": sha, "build_id": build_id}


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
        for key in [
            "event",
            "badge",
            "stage",
            "trace_id",
            "session_id",
            "user_id",
            "request_id",
            "channel",
            "platform",
            "intent",
            "current_state",
            "dialog_phase",
            "escalation_level",
            "fallback_type",
            "root_cause",
            "error_type",
            "error",
            "duration_ms",
            "latency_ms",
            "status_code",
            "status",
            "task_name",
            "task_id",
            "queue",
            "attempt",
            "git_sha",
            "build_id",
            "model",
            "prompt_version",
            "messages_count",
            "products_count",
            "text_len",
            "text_preview",
            "has_image",
            "image_url_preview",
        ]:
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
        static_fields = {"service": service_name, **_get_build_info()}
        formatter = JSONFormatter(
            include_path=include_path,
            extra_fields=static_fields,
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
