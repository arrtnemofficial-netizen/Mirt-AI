"""Centralized logging configuration for debugging.

Provides:
- Color-coded terminal output (errors=red, warnings=yellow, info=green)
- Detailed context in log messages
- Easy toggle between DEBUG and INFO levels

Usage:
    from src.core.logging_config import setup_logging, get_logger
    
    # At bot startup:
    setup_logging(debug=True)
    
    # In any module:
    logger = get_logger(__name__)
    logger.info("📦 Processing message", extra={"session_id": "123"})
"""

from __future__ import annotations

import logging
import sys
from typing import Any


# =============================================================================
# ANSI COLOR CODES (for terminal)
# =============================================================================

class Colors:
    """ANSI escape codes for terminal colors."""
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"


# =============================================================================
# COLOR FORMATTER
# =============================================================================


class ColorFormatter(logging.Formatter):
    """Formatter that adds colors based on log level."""

    LEVEL_COLORS = {
        logging.DEBUG: Colors.GRAY,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.RED + Colors.BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        # Add color based on level
        color = self.LEVEL_COLORS.get(record.levelno, Colors.RESET)
        
        # Format the message
        record.levelname = f"{color}{record.levelname:8}{Colors.RESET}"
        
        # Add module info in cyan
        record.name = f"{Colors.CYAN}{record.name}{Colors.RESET}"
        
        return super().format(record)


# =============================================================================
# SETUP FUNCTION
# =============================================================================


_logging_configured = False


def setup_logging(
    debug: bool = False,
    log_file: str | None = None,
) -> None:
    """
    Configure logging for the application.
    
    Args:
        debug: If True, set level to DEBUG. Otherwise INFO.
        log_file: Optional file path to write logs.
    """
    global _logging_configured
    
    if _logging_configured:
        return
    
    level = logging.DEBUG if debug else logging.INFO
    
    # Create formatter
    fmt = "%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s"
    date_fmt = "%H:%M:%S"
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(ColorFormatter(fmt, datefmt=date_fmt))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
        root_logger.addHandler(file_handler)
    
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("hpack.hpack").setLevel(logging.WARNING)
    logging.getLogger("hpack.table").setLevel(logging.WARNING)
    logging.getLogger("h2").setLevel(logging.WARNING)
    logging.getLogger("psycopg").setLevel(logging.WARNING)
    logging.getLogger("psycopg.pq").setLevel(logging.WARNING)
    
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)


# =============================================================================
# CONTEXT HELPERS
# =============================================================================


def log_step(
    logger: logging.Logger,
    step_name: str,
    session_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a processing step with context."""
    ctx = f"[{session_id[:8]}...]" if session_id else ""
    details = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.info(f"▶ {step_name} {ctx} {details}".strip())


def log_success(
    logger: logging.Logger,
    action: str,
    session_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Log a successful operation."""
    ctx = f"[{session_id[:8]}...]" if session_id else ""
    details = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.info(f"✅ {action} {ctx} {details}".strip())


def log_error(
    logger: logging.Logger,
    action: str,
    error: Exception | str,
    session_id: str | None = None,
) -> None:
    """Log an error with context."""
    ctx = f"[{session_id[:8]}...]" if session_id else ""
    err_msg = str(error)[:200]
    logger.error(f"❌ {action} {ctx}: {err_msg}")


def log_warning(
    logger: logging.Logger,
    message: str,
    session_id: str | None = None,
) -> None:
    """Log a warning with context."""
    ctx = f"[{session_id[:8]}...]" if session_id else ""
    logger.warning(f"⚠️ {message} {ctx}".strip())


# =============================================================================
# STEP TRACKER
# =============================================================================


class StepTracker:
    """Track steps in a pipeline for debugging."""
    
    def __init__(self, logger: logging.Logger, session_id: str = ""):
        self.logger = logger
        self.session_id = session_id
        self.steps: list[str] = []
        self.current_step = 0
    
    def step(self, name: str, **details: Any) -> None:
        """Mark a step as starting."""
        self.current_step += 1
        self.steps.append(name)
        log_step(self.logger, f"[{self.current_step}] {name}", self.session_id, **details)
    
    def done(self, result: str = "OK") -> None:
        """Mark current step as done."""
        if self.steps:
            step_name = self.steps[-1]
            log_success(self.logger, f"[{self.current_step}] {step_name}", self.session_id, result=result)
    
    def fail(self, error: Exception | str) -> None:
        """Mark current step as failed."""
        if self.steps:
            step_name = self.steps[-1]
            log_error(self.logger, f"[{self.current_step}] {step_name}", error, self.session_id)
    
    def summary(self) -> str:
        """Get summary of completed steps."""
        return f"Completed {self.current_step} steps: {' → '.join(self.steps)}"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "setup_logging",
    "get_logger",
    "log_step",
    "log_success", 
    "log_error",
    "log_warning",
    "StepTracker",
    "Colors",
]
