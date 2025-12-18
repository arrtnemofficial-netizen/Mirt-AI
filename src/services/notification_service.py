"""
Notification Service.
=====================
Handles sending alerts to managers via Telegram.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.conf.config import settings


logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications to managers."""

    def __init__(self) -> None:
        self.bot_token = settings.MANAGER_BOT_TOKEN.get_secret_value()
        self.chat_id = settings.MANAGER_CHAT_ID

    @staticmethod
    def _truncate(value: str | None, limit: int) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)] + "…"

    def _build_manager_message(
        self,
        *,
        session_id: str,
        reason: str,
        user_context: str | None,
        details: dict[str, Any] | None,
    ) -> str:
        details = details or {}

        trace_id = str(details.get("trace_id") or "").strip()
        dialog_phase = str(details.get("dialog_phase") or "").strip()
        current_state = str(details.get("current_state") or "").strip()
        intent = str(details.get("intent") or "").strip()

        customer_name = str(details.get("customer_name") or "").strip()
        customer_phone = str(details.get("customer_phone") or "").strip()
        customer_city = str(details.get("customer_city") or "").strip()
        customer_nova_poshta = str(details.get("customer_nova_poshta") or "").strip()

        payment_method = str(details.get("payment_method") or "").strip()
        payment_amount = details.get("payment_amount")
        payment_confirmed = details.get("payment_confirmed")
        payment_proof_received = details.get("payment_proof_received")
        payment_proof_via = str(details.get("payment_proof_via") or "").strip()
        payment_proof_url = str(details.get("payment_proof_url") or "").strip()

        products = details.get("products")
        products_lines: list[str] = []
        if isinstance(products, list):
            for p in products[:6]:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("name") or "").strip()
                size = str(p.get("size") or "").strip()
                color = str(p.get("color") or "").strip()
                price = p.get("price")
                if not name:
                    continue
                suffix_parts: list[str] = []
                if size:
                    suffix_parts.append(size)
                if color:
                    suffix_parts.append(color)
                if isinstance(price, (int, float)) and price > 0:
                    suffix_parts.append(f"₴{int(price)}")
                suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
                products_lines.append(f"- {self._truncate(name, 80)}{suffix}")

        lines: list[str] = [
            "🚨 Потрібен менеджер",
            f"Причина: {self._truncate(reason, 200) or '—'}",
            f"Session: `{self._truncate(session_id, 80)}`",
        ]
        if trace_id:
            lines.append(f"Trace: `{self._truncate(trace_id, 80)}`")
        if dialog_phase or current_state:
            lines.append(
                f"Стадія: {self._truncate(dialog_phase, 60) or '?'} / {self._truncate(current_state, 60) or '?'}"
            )
        if intent:
            lines.append(f"Intent: {self._truncate(intent, 60)}")

        if customer_name or customer_phone:
            who = " ".join([p for p in [customer_name, customer_phone] if p]).strip()
            lines.append(f"Клієнт: {self._truncate(who, 120)}")
        if customer_city or customer_nova_poshta:
            where = ", ".join([p for p in [customer_city, customer_nova_poshta] if p]).strip()
            lines.append(f"Доставка: {self._truncate(where, 140)}")

        payment_bits: list[str] = []
        if payment_method:
            payment_bits.append(payment_method)
        if isinstance(payment_amount, (int, float)) and payment_amount:
            payment_bits.append(f"сума {int(payment_amount)}")
        if payment_confirmed is True:
            payment_bits.append("підтверджено")
        if payment_proof_received is True:
            via = payment_proof_via or "proof"
            payment_bits.append(f"пруф: {via}")
        if payment_bits:
            lines.append(f"Оплата: {', '.join(payment_bits)}")
        if payment_proof_url:
            lines.append(f"Пруф URL: {self._truncate(payment_proof_url, 200)}")

        if products_lines:
            lines.append("Товари:")
            lines.extend(products_lines)

        ctx = self._truncate(user_context, 800)
        if ctx:
            lines.append("Останнє від клієнта:")
            lines.append(ctx)

        message = "\n".join(lines).strip()
        return self._truncate(message, 3900)

    async def send_escalation_alert(
        self,
        session_id: str,
        reason: str,
        user_context: str | None = None,
        details: dict[str, Any] | None = None,
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

        message = self._build_manager_message(
            session_id=session_id,
            reason=reason,
            user_context=user_context,
            details=details,
        )

        return await self._send_telegram_message(message)

    async def _send_telegram_message(self, text: str) -> bool:
        """Send raw message to Telegram."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        # Try with Markdown first, fallback to plain text if parsing fails
        for parse_mode in ["Markdown", None]:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            logger.info("Manager notification sent successfully")
                            return True
                        
                        # If Markdown parsing failed, try without it
                        resp_text = await response.text()
                        if parse_mode == "Markdown" and "parse entities" in resp_text:
                            logger.warning("Markdown parsing failed, retrying without parse_mode")
                            continue
                        
                        logger.error(
                            "Failed to send notification: %s %s",
                            response.status,
                            resp_text,
                        )
                        return False
            except Exception as e:
                logger.error("Notification error: %s", e)
                return False
        
        return False
