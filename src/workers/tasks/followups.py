"""Follow-up background tasks.

These tasks handle:
- Sending follow-up messages to inactive users
- Checking scheduled follow-ups based on FOLLOWUP_DELAYS_HOURS
- Sending messages via Telegram or ManyChat
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from celery import shared_task

from src.conf.config import settings
from src.core.constants import DBTable
from src.services.conversation import next_followup_due_at, run_followups
from src.services.storage import create_message_store
# PostgreSQL only - no Supabase dependency


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.followups.send_followup",
)
def send_followup(
    self,
    session_id: str,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Send a follow-up message for a session.

    Args:
        session_id: The session ID to check for follow-up
        channel: Delivery channel ("telegram" or "manychat")
        chat_id: Chat ID for sending the message

    Returns:
        dict with status and follow-up details
    """
    logger.info(
        "[WORKER:FOLLOWUP] Checking followup for session=%s channel=%s",
        session_id,
        channel,
    )

    try:
        now = datetime.now(UTC)
        current_hour = now.hour
        
        # Night mode: 23:00-07:00 UTC
        is_night_mode = current_hour >= 23 or current_hour < 7
        
        message_store = create_message_store()
        followup = run_followups(
            session_id=session_id,
            message_store=message_store,
            now=now,
        )

        if not followup:
            logger.info(
                "[WORKER:FOLLOWUP] No followup needed for session %s",
                session_id,
            )
            return {
                "status": "skipped",
                "session_id": session_id,
                "reason": "not_due",
            }

        # Use night message if in night mode
        if is_night_mode:
            from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header
            
            night_bubbles = get_snippet_by_header("FOLLOWUP_NIGHT")
            night_content = (
                "".join(night_bubbles)
                if night_bubbles
                else "?????????? ??'??????? ? ???? ?????? ??"
            )
            followup.content = night_content
            logger.info(
                "[WORKER:FOLLOWUP] Using night mode message for session %s (hour=%d)",
                session_id,
                current_hour,
            )

        # Send via appropriate channel
        if channel == "telegram" and chat_id:
            _send_telegram_followup(chat_id, followup.content)
        elif channel == "manychat" and chat_id:
            _send_manychat_followup(chat_id, followup.content)

        logger.info(
            "[WORKER:FOLLOWUP] Followup sent for session %s: %s",
            session_id,
            followup.content[:50],
        )

        # If this is the 23h followup (index 2), schedule escalation after 1 hour
        followup_index = None
        for tag in followup.tags:
            if tag.startswith("followup-sent-"):
                try:
                    followup_index = int(tag.split("-")[-1])
                    break
                except (ValueError, IndexError):
                    pass

        if followup_index == 2:  # 23h followup
            logger.info(
                "[WORKER:FOLLOWUP] Scheduling 24h escalation for session %s (1 hour delay)",
                session_id,
            )
            handle_24h_followup_escalation.apply_async(
                kwargs={
                    "session_id": session_id,
                    "channel": channel,
                    "chat_id": chat_id,
                },
                countdown=3600,  # 1 hour in seconds
            )

        return {
            "status": "sent",
            "session_id": session_id,
            "content": followup.content,
            "tags": followup.tags,
            "channel": channel,
        }

    except Exception as e:
        logger.exception(
            "[WORKER:FOLLOWUP] Error sending followup for session %s: %s",
            session_id,
            e,
        )
        raise


@shared_task(
    bind=True,
    name="src.workers.tasks.followups.check_all_sessions_for_followups",
)
def check_all_sessions_for_followups(self) -> dict:
    """Check all sessions and queue follow-up tasks for eligible ones.

    This is a periodic task that runs via Celery Beat.
    It finds sessions where follow-up is due based on last activity
    and the configured FOLLOWUP_DELAYS_HOURS schedule.

    Returns:
        dict with count of queued tasks
    """
    logger.info("[WORKER:FOLLOWUP] Starting periodic followup check")

    # Use PostgreSQL
    try:
        import psycopg
        from psycopg.rows import dict_row
        from src.services.storage import get_postgres_url
        
        # Get sessions with their chat info from PostgreSQL
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            logger.warning("[WORKER:FOLLOWUP] PostgreSQL not configured, skipping")
            return {"status": "skipped", "reason": "no_postgres"}
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT DISTINCT session_id, user_id FROM {DBTable.MESSAGES}"
                )
                rows = cur.fetchall()
        
        if not rows:
            return {"status": "ok", "queued": 0}

        # Get unique sessions with user mapping
        sessions: dict[str, int | None] = {}
        for row in rows:
            sid = row.get("session_id")
            if sid and sid not in sessions:
                sessions[sid] = row.get("user_id")

        message_store = create_message_store()
        now = datetime.now(UTC)
        queued = 0

        for session_id, _user_id in sessions.items():
            # Check if followup is due
            messages = message_store.list(session_id)
            due_at = next_followup_due_at(messages)

            if due_at and now >= due_at:
                # Queue follow-up task
                # Default to telegram, chat_id is session_id for telegram
                send_followup.delay(
                    session_id=session_id,
                    channel="telegram",
                    chat_id=session_id,
                )
                queued += 1

        logger.info(
            "[WORKER:FOLLOWUP] Queued %d followup tasks",
            queued,
        )
        return {"status": "ok", "queued": queued}

    except Exception as e:
        logger.exception("[WORKER:FOLLOWUP] Error in periodic check: %s", e)
        return {"status": "error", "error": str(e)}


@shared_task(
    bind=True,
    name="src.workers.tasks.followups.schedule_followup",
)
def schedule_followup(
    self,
    session_id: str,
    delay_hours: int,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Schedule a follow-up to be sent after a delay.

    This is called after each user interaction to schedule
    the next follow-up based on the configured delays.

    Args:
        session_id: The session ID
        delay_hours: Hours to wait before sending
        channel: Delivery channel
        chat_id: Chat ID for delivery

    Returns:
        dict with scheduled task info
    """
    logger.info(
        "[WORKER:FOLLOWUP] Scheduling followup for session=%s in %dh",
        session_id,
        delay_hours,
    )

    # Schedule the send_followup task with countdown
    task = send_followup.apply_async(
        kwargs={
            "session_id": session_id,
            "channel": channel,
            "chat_id": chat_id,
        },
        countdown=delay_hours * 3600,  # Convert hours to seconds
    )

    return {
        "status": "scheduled",
        "session_id": session_id,
        "task_id": task.id,
        "delay_hours": delay_hours,
    }


def _send_telegram_followup(chat_id: str, text: str) -> None:
    """Send follow-up message via Telegram bot."""
    from aiogram import Bot

    from src.workers.sync_utils import run_sync

    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    if not token:
        logger.warning("[WORKER:FOLLOWUP] Telegram token not configured")
        return

    async def _send():
        bot = Bot(token=token)
        try:
            await bot.send_message(chat_id=int(chat_id), text=text)
        finally:
            await bot.session.close()

    run_sync(_send())


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
    name="src.workers.tasks.followups.handle_24h_followup_escalation",
)
def handle_24h_followup_escalation(
    self,
    session_id: str,
    channel: str = "telegram",
    chat_id: str | None = None,
) -> dict:
    """Handle escalation after 24h (23h followup + 1h wait).

    This task:
    1. Adds humanNeeded-wd tag via ManyChat (if channel is manychat)
    2. Sets Sitniks status to "AI Увага"
    3. Assigns to human manager

    Args:
        session_id: Session ID
        channel: Delivery channel
        chat_id: Chat/subscriber ID

    Returns:
        dict with escalation result
    """
    logger.info(
        "[WORKER:FOLLOWUP] Handling 24h escalation for session=%s channel=%s",
        session_id,
        channel,
    )

    try:
        # Get user_id from PostgreSQL messages table
        import psycopg
        from psycopg.rows import dict_row
        from src.services.storage import get_postgres_url
        from src.conf.config import settings
        
        try:
            postgres_url = get_postgres_url()
        except ValueError:
            logger.warning(
                "[WORKER:FOLLOWUP] PostgreSQL not configured, skipping escalation",
            )
            return {"status": "skipped", "reason": "no_postgres"}
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT user_id
                    FROM {DBTable.MESSAGES}
                    WHERE session_id = %s
                    AND user_id IS NOT NULL
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
        
        user_id = row.get("user_id") if row else None

        if not user_id:
            logger.warning(
                "[WORKER:FOLLOWUP] No user_id found for session %s, skipping escalation",
                session_id,
            )
            return {"status": "skipped", "reason": "no_user_id"}

        # 1. Add humanNeeded-wd tag via ManyChat if channel is manychat
        if channel == "manychat" and chat_id:
            from src.integrations.manychat.api_client import get_manychat_client
            from src.workers.sync_utils import run_sync

            manychat_client = get_manychat_client()
            if manychat_client.is_configured:
                async def _add_tag():
                    return await manychat_client.add_tag(chat_id, "humanNeeded-wd")

                try:
                    run_sync(_add_tag())
                    logger.info(
                        "[WORKER:FOLLOWUP] Added humanNeeded-wd tag to ManyChat subscriber %s",
                        chat_id,
                    )
                except Exception as e:
                    logger.warning(
                        "[WORKER:FOLLOWUP] Failed to add ManyChat tag: %s",
                        e,
                    )

        # 2. Set Sitniks status to "AI Увага" and assign manager
        from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
        from src.workers.sync_utils import run_sync

        sitniks_service = get_sitniks_chat_service()
        if sitniks_service.enabled:
            async def _escalate():
                return await sitniks_service.handle_escalation(str(user_id))

            try:
                escalation_result = run_sync(_escalate())
                logger.info(
                    "[WORKER:FOLLOWUP] Escalation result for user %s: %s",
                    user_id,
                    escalation_result,
                )
            except Exception as e:
                logger.warning(
                    "[WORKER:FOLLOWUP] Failed to escalate in Sitniks: %s",
                    e,
                )

        return {
            "status": "escalated",
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
        }

    except Exception as e:
        logger.exception(
            "[WORKER:FOLLOWUP] Error handling 24h escalation for session %s: %s",
            session_id,
            e,
        )
        raise


def _send_manychat_followup(subscriber_id: str, text: str) -> None:
    """Send follow-up message via ManyChat API.
    
    Uses the existing ManyChatClient to send messages.
    """
    from src.integrations.manychat.api_client import get_manychat_client
    from src.workers.sync_utils import run_sync

    client = get_manychat_client()
    if not client.is_configured:
        logger.warning(
            "[WORKER:FOLLOWUP] ManyChat not configured, skipping followup for %s",
            subscriber_id,
        )
        return

    async def _send() -> bool:
        # Use set_custom_field to store follow-up text
        # ManyChat will pick this up and send via configured automation
        success = await client.set_custom_field(
            subscriber_id=subscriber_id,
            field_name="ai_followup_message",
            field_value=text[:500],  # ManyChat field limit
        )
        if success:
            # Add tag to trigger ManyChat automation flow
            await client.add_tag(subscriber_id, "ai_followup_pending")
        return success

    try:
        result = run_sync(_send())
        if result:
            logger.info(
                "[WORKER:FOLLOWUP] ManyChat followup queued for %s: %s",
                subscriber_id,
                text[:50],
            )
        else:
            logger.error(
                "[WORKER:FOLLOWUP] Failed to queue ManyChat followup for %s",
                subscriber_id,
            )
    except Exception as e:
        logger.exception(
            "[WORKER:FOLLOWUP] Error sending ManyChat followup for %s: %s",
            subscriber_id,
            e,
        )
