"""
Observability - Logfire Integration for PydanticAI.
====================================================
"Сліпий снайпер не стріляє."

Logfire дає тобі:
- Трейси: Graph Node -> Agent Run -> Tool Call -> DB Query
- Метрики: latency, token count, cost
- Алерти: якщо агент тупить

Вмикай у main.py ПЕРШИМ РЯДКОМ!
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def configure_logfire() -> bool:
    """
    Configure Logfire instrumentation.

    Call this ONCE at app startup (in main.py).

    Returns:
        True if configured successfully, False otherwise.
    """
    # Check if Logfire is enabled
    logfire_token = os.getenv("LOGFIRE_TOKEN")
    if not logfire_token:
        logger.warning(
            "LOGFIRE_TOKEN not set. Observability disabled. Set LOGFIRE_TOKEN to enable tracing."
        )
        return False

    try:
        import logfire

        # Configure Logfire
        logfire.configure(
            token=logfire_token,
            service_name="mirt-ai-agent",
            service_version=os.getenv("APP_VERSION", "1.0.0"),
            environment=os.getenv("ENV", "development"),
        )

        # Instrument PydanticAI - this is THE key line
        logfire.instrument_pydantic_ai()

        logger.info("Logfire configured successfully for PydanticAI")
        return True

    except ImportError:
        logger.warning("logfire package not installed. Run: pip install logfire")
        return False
    except Exception as e:
        logger.error("Failed to configure Logfire: %s", e)
        return False


def instrument_langgraph() -> bool:
    """
    Instrument LangGraph for tracing.

    This wraps graph execution with spans.
    """
    try:
        import logfire

        # LangGraph uses LangChain callbacks
        # Logfire can instrument these (if available)
        if hasattr(logfire, "instrument_langchain"):
            logfire.instrument_langchain()  # type: ignore[attr-defined]
            logger.info("LangGraph instrumentation enabled")
            return True

        logger.debug("instrument_langchain not available in this logfire version")
        return False

    except ImportError:
        logger.debug("LangChain/LangGraph instrumentation not available")
        return False
    except Exception as e:
        logger.warning("Failed to instrument LangGraph: %s", e)
        return False


def setup_observability() -> None:
    """
    Full observability setup.

    Call this at app startup:

        from src.agents.pydantic.observability import setup_observability
        setup_observability()
    """
    # Configure Logfire
    logfire_ok = configure_logfire()

    # Instrument LangGraph if Logfire is working
    if logfire_ok:
        instrument_langgraph()

    # Always set up basic structured logging
    _setup_structured_logging()


def _setup_structured_logging() -> None:
    """Configure structured logging for better observability."""
    import logging

    # Use JSON format for production
    env = os.getenv("ENV", "development")

    if env == "production":
        try:
            import json

            class JsonFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    log_obj = {
                        "timestamp": self.formatTime(record),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                    if record.exc_info:
                        log_obj["exception"] = self.formatException(record.exc_info)
                    return json.dumps(log_obj)

            # Apply to root logger
            root = logging.getLogger()
            for handler in root.handlers:
                handler.setFormatter(JsonFormatter())

        except Exception:
            pass  # Fall back to default formatting
