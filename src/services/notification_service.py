"""
Notification Service.
=====================
Handles sending alerts to managers via Telegram.
"""

from __future__ import annotations

import logging

import aiohttp

from src.conf.config import settings


logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications to managers."""

    def __init__(self) -> None:
        self.bot_token = settings.MANAGER_BOT_TOKEN.get_secret_value()
        self.chat_id = settings.MANAGER_CHAT_ID

    async def send_escalation_alert(
        self,
        session_id: str,
        reason: str,
        user_context: str | None = None,
    ) -> bool:
        """
        Send escalation alert to manager.

        Args:
            session_id: ID of the user session
            reason: Reason for escalation
            user_context: Optional context (e.g. last user message)
        """
        if not self.bot_token or not self.chat_id:
            logger.warning("Manager notification disabled: missing config")
            return False

        message = (
            f"🚨 **ESCALATION ALERT** 🚨\n\n"
            f"**Session ID:** `{session_id}`\n"
            f"**Reason:** {reason}\n"
        )

        if user_context:
            message += f"\n**Context:**\n{user_context}"

        return await self._send_telegram_message(message)

    async def _send_telegram_message(self, text: str) -> bool:
        """Send raw message to Telegram."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info("Manager notification sent successfully")
                        return True
                    else:
                        logger.error(
                            "Failed to send notification: %s %s",
                            response.status,
                            await response.text(),
                        )
                        return False
        except Exception as e:
            logger.error("Notification error: %s", e)
            return False
