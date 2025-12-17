"""Celery tasks for ManyChat message processing (durable)."""

from __future__ import annotations

import logging
from typing import Any

from src.conf.config import settings
from src.workers.sync_utils import run_sync

logger = logging.getLogger(__name__)


def process_manychat_message(
    user_id: str,
    text: str,
    image_url: str | None = None,
    channel: str = "instagram",
    subscriber_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process ManyChat message through AI and push response.
    
    This task replaces BackgroundTasks for durable processing.
    """
    from src.integrations.manychat.async_service import get_manychat_async_service
    from src.server.dependencies import get_session_store

    try:
        # Get services
        store = get_session_store()
        service = get_manychat_async_service(store)
        
        # Process message and push response
        coro = service.process_message_async(
            user_id=user_id,
            text=text,
            image_url=image_url,
            channel=channel,
            subscriber_data=subscriber_data,
        )
        result = run_sync(coro)
        
        logger.info(
            "[MANYCHAT_TASK] Processed message for user=%s channel=%s",
            user_id,
            channel,
        )
        
        return {
            "status": "success",
            "user_id": user_id,
            "response_sent": True,
        }
        
    except Exception as e:
        logger.error(
            "[MANYCHAT_TASK] Failed to process message for user=%s: %s",
            user_id,
            e,
            exc_info=True,
        )
        
        # In production, you might want to retry or send error notification
        return {
            "status": "error",
            "user_id": user_id,
            "error": str(e),
        }
