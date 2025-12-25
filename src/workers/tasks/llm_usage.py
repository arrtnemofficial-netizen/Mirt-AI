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
from src.services.infra.supabase_client import get_supabase_client
from src.workers.exceptions import DatabaseError, PermanentError, RetryableError


logger = logging.getLogger(__name__)


# Pricing per 1M tokens (USD) - GPT 5.1 ONLY
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "gpt-5.1": {"input": Decimal("2.50"), "output": Decimal("10.00")},
    # Default fallback (same as GPT 5.1)
    "default": {"input": Decimal("2.50"), "output": Decimal("10.00")},
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
        model: Model name (GPT-5.1 only)
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

    client = get_supabase_client()
    if not client:
        logger.warning("[WORKER:LLM_USAGE] Supabase not configured, skipping")
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Calculate cost
        cost_usd = calculate_cost(model, tokens_input, tokens_output)

        # Insert record
        record = {
            "user_id": user_id,
            "model": model,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": float(cost_usd),
            "created_at": datetime.now(UTC).isoformat(),
        }

        response = client.table(DBTable.LLM_USAGE).insert(record).execute()

        if response.data:
            record_id = response.data[0].get("id")
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

    client = get_supabase_client()
    if not client:
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Calculate date cutoff
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff.replace(day=cutoff.day - days) if cutoff.day > days else cutoff

        # Query usage records
        response = (
            client.table(DBTable.LLM_USAGE)
            .select("model, tokens_input, tokens_output, cost_usd")
            .eq("user_id", user_id)
            .gte("created_at", cutoff.isoformat())
            .execute()
        )

        if not response.data:
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

        for row in response.data:
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
        for model in by_model:
            by_model[model]["cost_usd"] = float(by_model[model]["cost_usd"])

        return {
            "status": "ok",
            "user_id": user_id,
            "days": days,
            "total_cost_usd": float(total_cost),
            "total_tokens_input": total_input,
            "total_tokens_output": total_output,
            "request_count": len(response.data),
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

    client = get_supabase_client()
    if not client:
        return {"status": "skipped", "reason": "no_supabase"}

    try:
        # Get today's usage
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        response = (
            client.table(DBTable.LLM_USAGE)
            .select("model, tokens_input, tokens_output, cost_usd, user_id")
            .gte("created_at", today.isoformat())
            .execute()
        )

        if not response.data:
            return {
                "status": "ok",
                "date": today.date().isoformat(),
                "total_cost_usd": 0,
                "request_count": 0,
                "unique_users": 0,
            }

        total_cost = sum(Decimal(str(row["cost_usd"])) for row in response.data)
        unique_users = len({row["user_id"] for row in response.data if row["user_id"]})

        logger.info(
            "[WORKER:LLM_USAGE] Daily aggregate: $%.4f, %d requests, %d users",
            total_cost,
            len(response.data),
            unique_users,
        )

        return {
            "status": "ok",
            "date": today.date().isoformat(),
            "total_cost_usd": float(total_cost),
            "request_count": len(response.data),
            "unique_users": unique_users,
        }

    except Exception as e:
        logger.exception("[WORKER:LLM_USAGE] Error in daily aggregate: %s", e)
        return {"status": "error", "error": str(e)}
