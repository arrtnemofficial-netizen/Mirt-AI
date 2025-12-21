"""
Memory background tasks for decay, cleanup, and summaries.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.services.domain.memory.memory_service import MemoryService
from src.services.infra.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


# =============================================================================
# CORE MAINTENANCE TASKS
# =============================================================================


async def apply_time_decay() -> dict[str, int]:
    """
     time decay   .

     importance  ,    .
       ""    .

    Returns:
        Stats dict with affected counts
    """
    logger.info("Starting memory time decay...")
    start = datetime.now(UTC)

    memory_service = MemoryService()

    if not memory_service.enabled:
        logger.warning("Memory service disabled, skipping time decay")
        return {"affected": 0, "error": "disabled"}

    try:
        affected = await memory_service.apply_time_decay()

        elapsed = (datetime.now(UTC) - start).total_seconds()
        logger.info("Time decay complete: %d facts affected in %.2fs", affected, elapsed)

        return {
            "affected": affected,
            "elapsed_seconds": elapsed,
            "timestamp": start.isoformat(),
        }

    except Exception as e:
        logger.error("Time decay failed: %s", e)
        return {"affected": 0, "error": str(e)}


async def cleanup_expired() -> dict[str, int]:
    """
     () expired .

      expires_at < now()    is_active=False.

    Returns:
        Stats dict with cleaned counts
    """
    logger.info("Starting expired memories cleanup...")
    start = datetime.now(UTC)

    memory_service = MemoryService()

    if not memory_service.enabled:
        logger.warning("Memory service disabled, skipping cleanup")
        return {"cleaned": 0, "error": "disabled"}

    try:
        cleaned = await memory_service.cleanup_expired()

        elapsed = (datetime.now(UTC) - start).total_seconds()
        logger.info("Cleanup complete: %d expired facts deactivated in %.2fs", cleaned, elapsed)

        return {
            "cleaned": cleaned,
            "elapsed_seconds": elapsed,
            "timestamp": start.isoformat(),
        }

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {"cleaned": 0, "error": str(e)}


async def generate_user_summary(user_id: str) -> dict[str, Any]:
    """
     summary   .

           summary.

    Args:
        user_id: User to generate summary for

    Returns:
        Summary stats
    """
    memory_service = MemoryService()

    if not memory_service.enabled:
        return {"error": "disabled"}

    try:
        # Get all facts for user
        facts = await memory_service.get_facts(user_id, limit=50, min_importance=0.3)

        if not facts:
            return {"user_id": user_id, "facts_count": 0, "summary": None}

        # Group facts by category
        categories = {}
        for fact in facts:
            cat = fact.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(fact.content)

        # Build summary text
        summary_parts = []
        for cat, contents in categories.items():
            summary_parts.append(f"{cat}: {'; '.join(contents[:3])}")

        summary_text = " | ".join(summary_parts)

        # Extract key facts (top 5 by importance)
        key_facts = [f.content for f in sorted(facts, key=lambda x: x.importance, reverse=True)[:5]]

        # Save summary
        result = await memory_service.save_summary(
            user_id=user_id,
            summary_text=summary_text[:500],  # Limit length
            key_facts=key_facts,
            facts_count=len(facts),
        )

        return {
            "user_id": user_id,
            "facts_count": len(facts),
            "summary_saved": result is not None,
        }

    except Exception as e:
        logger.error("Failed to generate summary for user %s: %s", user_id, e)
        return {"user_id": user_id, "error": str(e)}


async def generate_summaries_for_active_users(days: int = 7) -> dict[str, Any]:
    """
     summaries   .

    Args:
        days: Consider users active if seen in last N days

    Returns:
        Stats dict
    """
    logger.info("Starting summary generation for active users (last %d days)...", days)
    start = datetime.now(UTC)

    client = get_supabase_client()
    if not client:
        logger.warning("Supabase client not available")
        return {"processed": 0, "error": "no_client"}

    try:
        # Get active users
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        response = (
            client.table("mirt_profiles").select("user_id").gte("last_seen_at", cutoff).execute()
        )

        if not response.data:
            logger.info("No active users found")
            return {"processed": 0}

        user_ids = [row["user_id"] for row in response.data]
        logger.info("Found %d active users", len(user_ids))

        # Generate summaries
        results = []
        for user_id in user_ids:
            result = await generate_user_summary(user_id)
            results.append(result)

        successful = sum(1 for r in results if r.get("summary_saved"))
        elapsed = (datetime.now(UTC) - start).total_seconds()

        logger.info(
            "Summary generation complete: %d/%d users in %.2fs",
            successful,
            len(user_ids),
            elapsed,
        )

        return {
            "processed": len(user_ids),
            "successful": successful,
            "elapsed_seconds": elapsed,
            "timestamp": start.isoformat(),
        }

    except Exception as e:
        logger.error("Summary generation failed: %s", e)
        return {"processed": 0, "error": str(e)}


async def memory_maintenance() -> dict[str, Any]:
    """
       .

    :
    1. Time decay
    2. Cleanup expired
    3. Generate summaries

    Returns:
        Combined stats from all tasks
    """
    logger.info("Starting full memory maintenance cycle...")
    start = datetime.now(UTC)

    results = {}

    # Step 1: Time decay
    results["time_decay"] = await apply_time_decay()

    # Step 2: Cleanup
    results["cleanup"] = await cleanup_expired()

    # Step 3: Summaries (only for users active in last 3 days)
    results["summaries"] = await generate_summaries_for_active_users(days=3)

    elapsed = (datetime.now(UTC) - start).total_seconds()
    results["total_elapsed_seconds"] = elapsed
    results["timestamp"] = start.isoformat()

    logger.info("Full maintenance complete in %.2fs", elapsed)

    return results


# =============================================================================
# CELERY TASKS (if Celery is available)
# =============================================================================

try:
    from celery import shared_task

    @shared_task(name="memory.apply_time_decay")
    def celery_apply_time_decay():
        """Celery task for time decay."""
        return asyncio.run(apply_time_decay())

    @shared_task(name="memory.cleanup_expired")
    def celery_cleanup_expired():
        """Celery task for cleanup."""
        return asyncio.run(cleanup_expired())

    @shared_task(name="memory.generate_summaries")
    def celery_generate_summaries(days: int = 7):
        """Celery task for summary generation."""
        return asyncio.run(generate_summaries_for_active_users(days))

    @shared_task(name="memory.maintenance")
    def celery_memory_maintenance():
        """Celery task for full maintenance."""
        return asyncio.run(memory_maintenance())

    logger.info("Celery memory tasks registered")

except ImportError:
    logger.debug("Celery not available, skipping task registration")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


def run_maintenance_cli():
    """CLI entry point for running maintenance manually."""
    import argparse

    parser = argparse.ArgumentParser(description="MIRT Memory Maintenance")
    parser.add_argument(
        "--task",
        choices=["decay", "cleanup", "summaries", "full"],
        default="full",
        help="Which task to run",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days for active user threshold (summaries only)",
    )

    args = parser.parse_args()

    if args.task == "decay":
        result = asyncio.run(apply_time_decay())
    elif args.task == "cleanup":
        result = asyncio.run(cleanup_expired())
    elif args.task == "summaries":
        result = asyncio.run(generate_summaries_for_active_users(args.days))
    else:
        result = asyncio.run(memory_maintenance())

    print(f"Result: {result}")
    return result


if __name__ == "__main__":
    run_maintenance_cli()
