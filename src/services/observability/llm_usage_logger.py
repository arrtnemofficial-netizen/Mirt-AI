"""
LLM Usage Logger - Best-effort logging for LLM API calls.
==========================================================
This module provides non-blocking, best-effort logging of LLM usage
to the llm_usage table. It never throws exceptions that could affect
the main conversation flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from src.core.constants import DBTable
from src.services.storage import get_postgres_url
from src.services.observability.billing import calculate_cost


logger = logging.getLogger(__name__)


async def log_llm_usage_best_effort(
    session_id: str | None,
    model: str | None,
    tokens_input: int,
    tokens_output: int,
    latency_ms: float,
    success: bool = True,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """
    Log LLM usage to llm_usage table (best-effort, non-blocking).
    
    This function:
    - Never throws exceptions that could affect the main flow
    - Uses short timeout to avoid blocking
    - Logs errors at debug/warning level only
    - Calculates cost_usd automatically
    
    Args:
        session_id: Session ID (optional)
        model: Model name (e.g., "gpt-4o-mini") - required for cost calculation
        tokens_input: Input tokens used
        tokens_output: Output tokens used
        latency_ms: Latency in milliseconds
        success: Whether the LLM call succeeded
        error_message: Error message if success=False
        metadata: Optional metadata dict (will be serialized to JSONB)
        user_id: User ID (optional)
    """
    # Validate required fields
    if not model:
        logger.debug("[LLM_USAGE] Skipping log: model is required")
        return

    if tokens_input < 0 or tokens_output < 0:
        logger.debug(
            "[LLM_USAGE] Skipping log: invalid token counts (in=%d, out=%d)",
            tokens_input,
            tokens_output,
        )
        return

    # Calculate cost
    try:
        cost_usd, cost_uah = calculate_cost(model, tokens_input, tokens_output)
    except Exception as e:
        logger.debug("[LLM_USAGE] Cost calculation failed: %s", e)
        cost_usd = Decimal("0")
        cost_uah = Decimal("0")

    # Prepare metadata (safe, minimal)
    metadata_json = None
    if metadata:
        try:
            # Ensure metadata is safe (no large snapshots, no PII)
            safe_metadata = _sanitize_metadata(metadata)
            metadata_json = json.dumps(safe_metadata)
        except Exception as e:
            logger.debug("[LLM_USAGE] Metadata serialization failed: %s", e)
            metadata_json = None

    # Prepare values for INSERT
    created_at = datetime.now(UTC).isoformat()

    # Use asyncio.to_thread for non-blocking DB write
    # This ensures we don't block the event loop even if DB is slow
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                _write_to_db,
                user_id=user_id,
                session_id=session_id,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                cost_usd=float(cost_usd),
                cost_uah=float(cost_uah),
                latency_ms=int(latency_ms) if latency_ms >= 0 else None,
                success=success,
                error_message=error_message,
                metadata=metadata_json,
                created_at=created_at,
            ),
            timeout=2.0,  # Short timeout - don't block
        )
        logger.debug(
            "[LLM_USAGE] Logged usage: session=%s, model=%s, tokens=%d/%d, cost=$%.6f (%.2f UAH)",
            session_id or "?",
            model,
            tokens_input,
            tokens_output,
            cost_usd,
            cost_uah
        )
    except TimeoutError:
        logger.debug("[LLM_USAGE] DB write timeout (non-critical, skipping)")
    except Exception as e:
        # Never let logging errors affect the main flow
        logger.debug("[LLM_USAGE] DB write failed (non-critical): %s", str(e)[:200])


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize metadata to ensure it's safe for storage.
    
    Removes:
    - Large text fields (snapshots, full URLs with base64)
    - PII (if any)
    - Keeps only minimal, safe fields
    
    Args:
        metadata: Raw metadata dict
        
    Returns:
        Sanitized metadata dict
    """
    safe: dict[str, Any] = {}

    # Safe fields to keep
    safe_fields = {
        "dialog_phase",
        "current_state",
        "intent",
        "policy_case",
        "has_image",
        "confidence",
        "detected_product_id",
        "detected_product_name",
    }

    for key, value in metadata.items():
        if key in safe_fields:
            safe[key] = value
        elif key == "image_url":
            # Only keep host, not full URL (might contain base64 or sensitive data)
            if isinstance(value, str):
                try:
                    parsed = urlparse(value)
                    if parsed.hostname:
                        safe["image_url_host"] = parsed.hostname
                except Exception:
                    pass  # Skip if URL parsing fails
        elif key == "image_url_host":
            # Already safe
            safe[key] = value

    return safe


def _write_to_db(
    user_id: str | None,
    session_id: str | None,
    model: str,
    tokens_input: int,
    tokens_output: int,
    cost_usd: float,
    cost_uah: float,
    latency_ms: int | None,
    success: bool,
    error_message: str | None,
    metadata: str | None,
    created_at: str,
) -> None:
    """
    Write LLM usage record to PostgreSQL.
    
    This is a sync function that runs in asyncio.to_thread to avoid blocking.
    """
    try:
        postgres_url = get_postgres_url()
    except ValueError:
        logger.debug("[LLM_USAGE] PostgreSQL not configured, skipping")
        return

    # Use psycopg (sync) in thread to avoid async complexity
    import psycopg

    try:
        with psycopg.connect(postgres_url) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                    INSERT INTO {DBTable.LLM_USAGE}
                    (user_id, session_id, model, tokens_input, tokens_output, cost_usd, cost_uah,
                     latency_ms, success, error_message, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                (
                    user_id,
                    session_id,
                    model,
                    tokens_input,
                    tokens_output,
                    cost_usd,
                    cost_uah,
                    latency_ms,
                    success,
                    error_message,
                    metadata,
                    created_at,
                ),
            )
            conn.commit()
    except Exception:
        # Re-raise to be caught by caller
        raise

