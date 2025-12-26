"""LLM usage tracking background tasks.

These tasks handle:
- Recording LLM token usage to llm_usage table
- Calculating costs based on model pricing
- Aggregating usage statistics

Integrates with Supabase llm_usage table:
    - id (bigint)
    - user_id (bigint)
    - model (varchar)
    - tokens_input (int4)
    - tokens_output (int4)
    - cost_usd (numeric)
    - created_at (timestamptz)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from celery import shared_task

from src.core.constants import DBTable
# PostgreSQL only - no Supabase dependency
from src.workers.exceptions import DatabaseError, PermanentError, RetryableError


logger = logging.getLogger(__name__)


# Pricing per 1M tokens (USD) - update as needed
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
    "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
    "gpt-4-turbo": {"input": Decimal("10.00"), "output": Decimal("30.00")},
    "gpt-4": {"input": Decimal("30.00"), "output": Decimal("60.00")},
    "gpt-3.5-turbo": {"input": Decimal("0.50"), "output": Decimal("1.50")},
    "claude-3-5-sonnet": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-3-5-haiku": {"input": Decimal("0.25"), "output": Decimal("1.25")},
    # Default fallback
    "default": {"input": Decimal("1.00"), "output": Decimal("3.00")},
}


def calculate_cost(
    model: str,
    tokens_input: int,
    tokens_output: int,
) -> Decimal:
    """Calculate cost in USD for token usage.

    Args:
        model: Model name
        tokens_input: Input token count
        tokens_output: Output token count

    Returns:
        Cost in USD as Decimal
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

    # Calculate cost (pricing is per 1M tokens)
    input_cost = (Decimal(tokens_input) / Decimal(1_000_000)) * pricing["input"]
    output_cost = (Decimal(tokens_output) / Decimal(1_000_000)) * pricing["output"]

    return (input_cost + output_cost).quantize(Decimal("0.000001"))


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.llm_usage.record_usage",
    soft_time_limit=10,
    time_limit=15,
    queue="default",
)
def record_usage(
    self,
    user_id: int | None,
    model: str,
    tokens_input: int,
    tokens_output: int,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Record LLM usage to database.

    Args:
        user_id: User ID (optional)
        model: Model name (e.g., "gpt-4o-mini")
        tokens_input: Input tokens used
        tokens_output: Output tokens used
        session_id: Optional session ID for context
        metadata: Optional metadata

    Returns:
        dict with recording result
    """
    logger.info(
        "[WORKER:LLM_USAGE] Recording usage user=%s model=%s in=%d out=%d",
        user_id,
        model,
        tokens_input,
        tokens_output,
    )

    # Validate input
    if tokens_input < 0 or tokens_output < 0:
        raise PermanentError("Token counts cannot be negative", error_code="INVALID_INPUT")

    if not model:
        raise PermanentError("Model name is required", error_code="INVALID_INPUT")

    # Use PostgreSQL
    try:
        import psycopg
        from src.services.storage import get_postgres_url
        
        # Calculate cost
        cost_usd = calculate_cost(model, tokens_input, tokens_output)

        # Insert record into PostgreSQL
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            logger.warning("[WORKER:LLM_USAGE] PostgreSQL not configured, skipping")
            return {"status": "skipped", "reason": "no_postgres"}
        created_at = datetime.now(UTC).isoformat()
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {DBTable.LLM_USAGE}
                    (user_id, model, tokens_input, tokens_output, cost_usd, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        user_id,
                        model,
                        tokens_input,
                        tokens_output,
                        float(cost_usd),
                        created_at,
                    ),
                )
                record_id = cur.fetchone()[0]
                conn.commit()

        if record_id:
            logger.info(
                "[WORKER:LLM_USAGE] Recorded usage id=%s cost=$%.6f",
                record_id,
                cost_usd,
            )
            return {
                "status": "recorded",
                "id": record_id,
                "cost_usd": float(cost_usd),
                "model": model,
            }
        else:
            logger.warning("[WORKER:LLM_USAGE] Insert returned no data")
            return {"status": "unknown", "reason": "no_response_data"}

    except Exception as e:
        logger.exception("[WORKER:LLM_USAGE] Error recording usage: %s", e)
        raise DatabaseError(f"Failed to record LLM usage: {e}") from e


@shared_task(
    bind=True,
    name="src.workers.tasks.llm_usage.get_user_usage_summary",
    soft_time_limit=15,
    time_limit=20,
)
def get_user_usage_summary(
    self,
    user_id: int,
    days: int = 30,
) -> dict:
    """Get usage summary for a user.

    Args:
        user_id: User ID
        days: Number of days to look back

    Returns:
        dict with usage summary
    """
    logger.info(
        "[WORKER:LLM_USAGE] Getting usage summary user=%s days=%d",
        user_id,
        days,
    )

    # Use PostgreSQL
    try:
        import psycopg
        from psycopg.rows import dict_row
        from src.services.storage import get_postgres_url
        
        # Calculate date cutoff
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff.replace(day=cutoff.day - days) if cutoff.day > days else cutoff

        # Query usage records from PostgreSQL
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            return {"status": "skipped", "reason": "no_postgres"}
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT model, tokens_input, tokens_output, cost_usd
                    FROM {DBTable.LLM_USAGE}
                    WHERE user_id = %s
                    AND created_at >= %s
                    """,
                    (user_id, cutoff),
                )
                rows = cur.fetchall()

        if not rows:
            return {
                "status": "ok",
                "user_id": user_id,
                "total_cost_usd": 0,
                "total_tokens_input": 0,
                "total_tokens_output": 0,
                "request_count": 0,
                "by_model": {},
            }

        # Aggregate
        total_cost = Decimal("0")
        total_input = 0
        total_output = 0
        by_model: dict[str, dict[str, Any]] = {}

        for row in rows:
            model = row["model"]
            total_cost += Decimal(str(row["cost_usd"]))
            total_input += row["tokens_input"]
            total_output += row["tokens_output"]

            if model not in by_model:
                by_model[model] = {
                    "cost_usd": Decimal("0"),
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "count": 0,
                }
            by_model[model]["cost_usd"] += Decimal(str(row["cost_usd"]))
            by_model[model]["tokens_input"] += row["tokens_input"]
            by_model[model]["tokens_output"] += row["tokens_output"]
            by_model[model]["count"] += 1

        # Convert Decimal to float for JSON serialization
        for _model, stats in by_model.items():
            stats["cost_usd"] = float(stats["cost_usd"])

        return {
            "status": "ok",
            "user_id": user_id,
            "days": days,
            "total_cost_usd": float(total_cost),
            "total_tokens_input": total_input,
            "total_tokens_output": total_output,
            "request_count": len(rows),
            "by_model": by_model,
        }

    except Exception as e:
        logger.exception("[WORKER:LLM_USAGE] Error getting summary: %s", e)
        return {"status": "error", "error": str(e)}


@shared_task(
    bind=True,
    name="src.workers.tasks.llm_usage.aggregate_daily_usage",
)
def aggregate_daily_usage(self) -> dict:
    """Aggregate daily usage across all users.

    This is a periodic task that can run daily
    to generate usage reports.

    Returns:
        dict with daily aggregation
    """
    logger.info("[WORKER:LLM_USAGE] Aggregating daily usage")

    # Use PostgreSQL
    try:
        import psycopg
        from psycopg.rows import dict_row
        from src.services.storage import get_postgres_url
        
        # Get today's usage
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        # Query from PostgreSQL
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            return {"status": "skipped", "reason": "no_postgres"}
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT model, tokens_input, tokens_output, cost_usd, user_id
                    FROM {DBTable.LLM_USAGE}
                    WHERE created_at >= %s
                    """,
                    (today,),
                )
                rows = cur.fetchall()

        if not rows:
            return {
                "status": "ok",
                "date": today.date().isoformat(),
                "total_cost_usd": 0,
                "request_count": 0,
                "unique_users": 0,
            }

        total_cost = sum(Decimal(str(row["cost_usd"])) for row in rows)
        unique_users = len({row["user_id"] for row in rows if row["user_id"]})

        logger.info(
            "[WORKER:LLM_USAGE] Daily aggregate: $%.4f, %d requests, %d users",
            total_cost,
            len(rows),
            unique_users,
        )

        return {
            "status": "ok",
            "date": today.date().isoformat(),
            "total_cost_usd": float(total_cost),
            "request_count": len(rows),
            "unique_users": unique_users,
        }

    except Exception as e:
        logger.exception("[WORKER:LLM_USAGE] Error in daily aggregate: %s", e)
        return {"status": "error", "error": str(e)}
