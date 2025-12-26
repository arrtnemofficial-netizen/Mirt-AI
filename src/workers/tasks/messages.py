"""Message processing tasks - THE CORE TASK.

This is the main task that processes incoming messages through the AI agent.
Webhooks should dispatch to this task for async processing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from celery import shared_task

from src.conf.config import settings
from src.workers.exceptions import (
    ExternalServiceError,
    PermanentError,
    RateLimitError,
    RetryableError,
)
from src.workers.sync_utils import run_sync


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RetryableError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.messages.process_message",
    soft_time_limit=55,
    time_limit=60,
    queue="llm",
)
def process_message(
    self,
    session_id: str,
    user_message: str,
    user_id: str | None = None,
    platform: str = "telegram",
    chat_id: str | None = None,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process a user message through the AI agent.

    This is THE MAIN TASK - all incoming messages should go through here.

    Args:
        session_id: Unique session identifier
        user_message: The user's message text
        user_id: Optional user ID for personalization
        platform: Source platform (telegram, manychat, api)
        chat_id: Chat ID for response delivery
        message_id: Original message ID for idempotency
        metadata: Additional context (user info, etc)

    Returns:
        dict with agent response and metadata
    """
    logger.info(
        "[WORKER:MSG] Processing message session=%s platform=%s attempt=%d",
        session_id,
        platform,
        self.request.retries + 1,
    )

    if not user_message or not user_message.strip():
        raise PermanentError("Empty message", error_code="EMPTY_MESSAGE")

    try:
        # Import agent here to avoid circular imports
        from src.agents import get_active_graph as create_agent_graph  # Fixed typo: was src.agent
        from src.services.storage import StoredMessage, create_message_store

        # Get or create message store
        message_store = create_message_store()

        # Store user message
        user_msg = StoredMessage(
            session_id=session_id,
            role="user",
            content=user_message.strip(),
            created_at=datetime.now(UTC),
            metadata=metadata or {},
        )
        message_store.append(user_msg)

        # Get conversation history
        history = message_store.list(session_id, limit=20)

        # Build context for agent
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "platform": platform,
            "history": [{"role": m.role, "content": m.content} for m in history],
            "metadata": metadata or {},
        }

        # Run agent (async)
        async def _run_agent():
            graph = create_agent_graph()
            result = await graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": user_message}],
                    "context": context,
                }
            )
            return result

        result = run_sync(_run_agent())

        # Extract response
        response_text = ""
        if result and "messages" in result:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                response_text = last_msg.content
            elif isinstance(last_msg, dict):
                response_text = last_msg.get("content", "")

        if not response_text:
            from src.core.human_responses import get_human_response

            response_text = get_human_response("timeout")

        # Store assistant response
        assistant_msg = StoredMessage(
            session_id=session_id,
            role="assistant",
            content=response_text,
            created_at=datetime.now(UTC),
        )
        message_store.append(assistant_msg)

        logger.info(
            "[WORKER:MSG] Message processed session=%s response_len=%d",
            session_id,
            len(response_text),
        )

        return {
            "status": "success",
            "session_id": session_id,
            "response": response_text,
            "response_length": len(response_text),
            "platform": platform,
            "chat_id": chat_id,
        }

    except PermanentError:
        raise
    except RateLimitError as e:
        logger.warning("[WORKER:MSG] Rate limited: %s", e)
        raise
    except Exception as e:
        error_msg = str(e)
        if "rate" in error_msg.lower() or "429" in error_msg:
            raise RateLimitError(f"LLM rate limit: {e}", retry_after=60) from e
        if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
            raise ExternalServiceError("llm", error_msg) from e

        logger.exception("[WORKER:MSG] Error processing message: %s", e)
        raise RetryableError(f"Message processing failed: {e}") from e


@shared_task(
    bind=True,
    name="src.workers.tasks.messages.send_response",
    soft_time_limit=25,
    time_limit=30,
    queue="webhooks",
)
def send_response(
    self,
    platform: str,
    chat_id: str,
    response_text: str,
    reply_to_message_id: str | None = None,
) -> dict[str, Any]:
    """Send a response back to the user on their platform.

    This task handles response delivery after message processing.

    Args:
        platform: Target platform (telegram, manychat)
        chat_id: Chat/user ID on the platform
        response_text: Text to send
        reply_to_message_id: Optional message to reply to

    Returns:
        dict with delivery status
    """
    logger.info(
        "[WORKER:SEND] Sending response to %s chat=%s len=%d",
        platform,
        chat_id,
        len(response_text),
    )

    try:
        if platform == "telegram":

            async def _send_telegram():
                from aiogram import Bot

                bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
                try:
                    await bot.send_message(
                        chat_id=int(chat_id),
                        text=response_text,
                        reply_to_message_id=int(reply_to_message_id)
                        if reply_to_message_id
                        else None,
                    )
                    return True
                finally:
                    await bot.session.close()

            success = run_sync(_send_telegram())
            return {"status": "sent" if success else "failed", "platform": platform}

        elif platform == "manychat":
            # ManyChat sends response in webhook response, not separately
            logger.info("[WORKER:SEND] ManyChat - response sent via webhook")
            return {"status": "webhook_response", "platform": platform}

        else:
            logger.warning("[WORKER:SEND] Unknown platform: %s", platform)
            return {"status": "unknown_platform", "platform": platform}

    except Exception as e:
        logger.exception("[WORKER:SEND] Failed to send response: %s", e)
        raise ExternalServiceError(platform, str(e)) from e


@shared_task(
    bind=True,
    name="src.workers.tasks.messages.process_and_respond",
    soft_time_limit=85,
    time_limit=90,
    queue="llm",
)
def process_and_respond(
    self,
    session_id: str,
    user_message: str,
    platform: str,
    chat_id: str,
    user_id: str | None = None,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process message AND send response - combined task.

    Use this for fire-and-forget webhook processing.
    Chains process_message -> send_response.

    Args:
        session_id: Session ID
        user_message: User's message
        platform: Source platform
        chat_id: Chat ID for response
        user_id: Optional user ID
        message_id: Original message ID
        metadata: Additional context

    Returns:
        dict with processing and delivery status
    """
    # Process
    result = process_message(
        session_id=session_id,
        user_message=user_message,
        user_id=user_id,
        platform=platform,
        chat_id=chat_id,
        message_id=message_id,
        metadata=metadata,
    )

    if result["status"] != "success":
        return result

    # Send response
    send_result = send_response(
        platform=platform,
        chat_id=chat_id,
        response_text=result["response"],
        reply_to_message_id=message_id,
    )

    return {
        **result,
        "delivery": send_result,
    }
