"""Task dispatcher that routes to Celery or sync execution.

When CELERY_ENABLED=true, tasks are queued to Celery workers.
When CELERY_ENABLED=false, tasks run synchronously (for dev/testing).

Features:
- Idempotency via webhook-based task IDs
- Consistent response format with queue info
- Trace ID propagation for observability
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.conf.config import settings
from src.workers.idempotency import webhook_task_id

from src.integrations.crm.snitkix import get_snitkix_client
from src.services.infra.supabase_client import get_supabase_client
from src.workers.sync_utils import run_sync

try:
    # Exported for tests (they patch src.workers.dispatcher.sync_order_status)
    from src.workers.tasks.crm import sync_order_status
except Exception:  # pragma: no cover
    sync_order_status = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


def _generate_trace_id() -> str:
    """Generate a trace ID for request tracking."""
    return uuid.uuid4().hex[:16]


def dispatch_summarization(session_id: str, user_id: int | None = None) -> dict:
    """Dispatch summarization task.

    Args:
        session_id: Session to summarize
        user_id: Optional user ID

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.summarization import summarize_session

        task = summarize_session.delay(session_id, user_id)
        logger.info("[DISPATCH] Queued summarization task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution
        from src.services.infra.message_store import create_message_store
        from src.services.domain.memory.summarization import run_retention

        message_store = create_message_store()
        summary = run_retention(session_id, message_store, user_id=user_id)
        return {"queued": False, "summary": summary}


def dispatch_followup(
    session_id: str,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Dispatch follow-up task.

    Args:
        session_id: Session ID
        channel: Delivery channel
        chat_id: Chat ID for delivery

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.followups import send_followup

        task = send_followup.delay(session_id, channel, chat_id)
        logger.info("[DISPATCH] Queued followup task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution
        from src.services.domain.engagement.followups import run_followups
        from src.services.infra.message_store import create_message_store

        message_store = create_message_store()
        followup = run_followups(session_id, message_store)
        return {
            "queued": False,
            "followup_created": bool(followup),
            "content": followup.content if followup else None,
        }


def schedule_followup(
    session_id: str,
    delay_hours: int,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Schedule a follow-up for later.

    When Celery is enabled, uses apply_async with countdown.
    When disabled, returns immediately (no scheduling).

    Args:
        session_id: Session ID
        delay_hours: Hours to wait
        channel: Delivery channel
        chat_id: Chat ID

    Returns:
        Scheduling info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.followups import schedule_followup as celery_schedule

        result = celery_schedule.delay(session_id, delay_hours, channel, chat_id)
        logger.info(
            "[DISPATCH] Scheduled followup for session %s in %dh, task=%s",
            session_id,
            delay_hours,
            result.id,
        )
        return {"scheduled": True, "task_id": result.id, "delay_hours": delay_hours}
    else:
        logger.info(
            "[DISPATCH] Celery disabled, followup scheduling skipped for %s",
            session_id,
        )
        return {"scheduled": False, "reason": "celery_disabled"}


def dispatch_crm_order_status(
    order_id: str,
    session_id: str,
    new_status: str | None = None,
) -> dict:
    """Dispatch CRM order status sync task.

    Args:
        order_id: CRM order ID
        session_id: Session ID to update
        new_status: New order status (if known from webhook)

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        if sync_order_status is None:
            raise RuntimeError("CRM task sync_order_status is not available")
        task = sync_order_status.delay(order_id, session_id, new_status)  # type: ignore[union-attr]
        logger.info("[DISPATCH] Queued CRM order status sync task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution
        if not settings.snitkix_enabled:
            return {"queued": False, "status": "crm_not_configured"}

        async def _sync():
            crm = get_snitkix_client()
            if not new_status:
                order_status = await crm.get_order_status(order_id)
                new_status = order_status.status if order_status else None

            if not new_status:
                return {"status": "error", "reason": "status_not_found"}

            # Update session state in Supabase
            client = get_supabase_client()
            if client:
                client.table("agent_sessions").update(
                    {
                        "order_status": new_status,
                        "order_id": order_id,
                    }
                ).eq("session_id", session_id).execute()

            return {
                "status": "synced",
                "order_id": order_id,
                "order_status": new_status,
                "session_id": session_id,
            }

        try:
            result = run_sync(_sync())
            return {"queued": False, **result}
        except Exception as e:
            logger.exception("[DISPATCH] Sync order status failed: %s", e)
            return {"queued": False, "status": "error", "error": str(e)}


def dispatch_crm_order(order_data: dict[str, Any]) -> dict:
    """Dispatch CRM order creation task.

    Args:
        order_data: Order data dictionary

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.crm import create_crm_order

        task = create_crm_order.delay(order_data)
        logger.info("[DISPATCH] Queued CRM order task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution - use run_sync instead of asyncio.run
        from src.integrations.crm.snitkix import get_snitkix_client
        from src.services.data.order_model import CustomerInfo, Order, OrderItem
        from src.workers.sync_utils import run_sync

        if not settings.snitkix_enabled:
            return {"queued": False, "status": "crm_not_configured"}

        customer_data = order_data.get("customer", {})
        customer = CustomerInfo(
            full_name=customer_data.get("full_name"),
            phone=customer_data.get("phone"),
            city=customer_data.get("city"),
            nova_poshta_branch=customer_data.get("nova_poshta_branch"),
            telegram_id=customer_data.get("telegram_id"),
            manychat_id=customer_data.get("manychat_id"),
        )

        items = []
        for item_data in order_data.get("items", []):
            items.append(
                OrderItem(
                    product_id=item_data.get("product_id", 0),
                    product_name=item_data.get("product_name", ""),
                    size=item_data.get("size", ""),
                    color=item_data.get("color", ""),
                    price=item_data.get("price", 0.0),
                )
            )

        order = Order(
            external_id=order_data.get("external_id", ""),
            customer=customer,
            items=items,
            source=order_data.get("source", "unknown"),
            source_id=order_data.get("source_id", ""),
        )

        async def _create():
            crm = get_snitkix_client()
            return await crm.create_order(order)

        response = run_sync(_create())
        return {
            "queued": False,
            "success": response.success,
            "order_id": response.order_id,
            "error": response.error,
        }


def dispatch_message(
    session_id: str,
    user_message: str,
    platform: str = "telegram",
    chat_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    fire_and_forget: bool = False,
) -> dict:
    """Dispatch message processing to Celery or sync.

    This is THE MAIN DISPATCHER for incoming messages.

    Args:
        session_id: Unique session ID
        user_message: User's message text
        platform: Source platform (telegram, manychat)
        chat_id: Chat ID for response delivery
        user_id: Optional user ID
        message_id: Original message ID for idempotency
        metadata: Additional context
        fire_and_forget: If True, don't wait for result (async only)

    Returns:
        Task result or queued task info
    """
    trace_id = _generate_trace_id()

    # Generate idempotent task ID
    task_id = webhook_task_id(platform, message_id, user_id or session_id, "process")

    logger.info(
        "[DISPATCH] Message trace=%s session=%s platform=%s",
        trace_id,
        session_id,
        platform,
    )

    if settings.CELERY_ENABLED:
        from src.workers.tasks.messages import process_and_respond, process_message

        if fire_and_forget and chat_id:
            # Fire and forget - process + send response
            task = process_and_respond.apply_async(
                kwargs={
                    "session_id": session_id,
                    "user_message": user_message,
                    "platform": platform,
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "message_id": message_id,
                    "metadata": metadata,
                },
                task_id=task_id,
            )
            logger.info("[DISPATCH] Queued fire-and-forget task %s", task.id)
            return {
                "queued": True,
                "task_id": task.id,
                "trace_id": trace_id,
                "mode": "fire_and_forget",
            }
        else:
            # Queue and optionally wait
            task = process_message.apply_async(
                kwargs={
                    "session_id": session_id,
                    "user_message": user_message,
                    "user_id": user_id,
                    "platform": platform,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "metadata": metadata,
                },
                task_id=task_id,
            )
            logger.info("[DISPATCH] Queued message task %s", task.id)
            return {
                "queued": True,
                "task_id": task.id,
                "trace_id": trace_id,
                "mode": "async",
            }
    else:
        # Sync execution
        from src.workers.sync_utils import run_sync

        async def _process_sync():
            from src.agents import (
                get_active_graph as create_agent_graph,  # Fixed typo: was src.agent
            )
            from src.services.infra.message_store import create_message_store

            message_store = create_message_store()
            history = message_store.list(session_id, limit=20)

            graph = create_agent_graph()
            result = await graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": user_message}],
                    "context": {
                        "session_id": session_id,
                        "user_id": user_id,
                        "platform": platform,
                        "history": [{"role": m.role, "content": m.content} for m in history],
                    },
                }
            )
            return result

        try:
            result = run_sync(_process_sync())
            response = ""
            if result and "messages" in result:
                last = result["messages"][-1]
                response = last.content if hasattr(last, "content") else last.get("content", "")

            return {
                "queued": False,
                "trace_id": trace_id,
                "response": response,
            }
        except Exception as e:
            logger.exception("[DISPATCH] Sync processing failed: %s", e)
            return {
                "queued": False,
                "trace_id": trace_id,
                "error": str(e),
            }


def dispatch_llm_usage(
    user_id: int | None,
    model: str,
    tokens_input: int,
    tokens_output: int,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Dispatch LLM usage recording.

    Args:
        user_id: User ID (optional)
        model: Model name
        tokens_input: Input token count
        tokens_output: Output token count
        session_id: Optional session ID
        metadata: Optional metadata

    Returns:
        Task result or async task info
    """
    if settings.CELERY_ENABLED:
        from src.workers.tasks.llm_usage import record_usage

        task = record_usage.delay(
            user_id=user_id,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            session_id=session_id,
            metadata=metadata,
        )
        logger.info("[DISPATCH] Queued LLM usage task %s", task.id)
        return {"queued": True, "task_id": task.id}
    else:
        # Sync execution - just log it
        from src.workers.tasks.llm_usage import calculate_cost

        cost = calculate_cost(model, tokens_input, tokens_output)
        logger.info(
            "[DISPATCH] LLM usage (sync): model=%s in=%d out=%d cost=$%.6f",
            model,
            tokens_input,
            tokens_output,
            cost,
        )
        return {
            "queued": False,
            "model": model,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": float(cost),
        }
