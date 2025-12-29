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

        # Add image URL if available (for vision escalations)
        image_url = str(details.get("image_url") or "").strip()
        if image_url:
            lines.append(f"Фото: {self._truncate(image_url, 200)}")

        # Add vision-specific details if available
        vision_identified = str(details.get("vision_identified") or "").strip()
        if vision_identified:
            lines.append(f"Vision визначив: {self._truncate(vision_identified, 100)}")

        confidence = details.get("confidence")
        if confidence is not None:
            lines.append(f"Confidence: {confidence:.0f}%")

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

        # If image_url is provided, try to send photo with caption
        # BUT: Skip sendPhoto for private CDN URLs (Instagram/Facebook CDN) - Telegram can't fetch them
        image_url = details.get("image_url") if details else None
        if image_url:
            # Check if URL is from private CDN (Instagram/Facebook)
            image_url_str = str(image_url).lower()
            is_private_cdn = (
                "lookaside.fbsbx.com" in image_url_str
                or "ig_messaging_cdn" in image_url_str
                or "fbcdn.net" in image_url_str
            )

            if is_private_cdn:
                # Private CDN → Telegram can't fetch, send text with URL instead
                logger.info("Skipping sendPhoto for private CDN URL, sending text with URL")
                message_with_url = f"{message}\n\n📷 Image URL: {image_url}"
                return await self._send_telegram_message(message_with_url)
            else:
                # Public URL → try sendPhoto
                return await self._send_telegram_photo(image_url, message)

        return await self._send_telegram_message(message)

    async def _send_telegram_photo(self, photo_url: str, caption: str, max_retries: int = 2) -> bool:
        """
        Send photo with caption to Telegram with retry and backoff.
        
        Args:
            photo_url: URL of the photo to send
            caption: Caption text (truncated to 1024 chars)
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if sent successfully, False otherwise (falls back to text message)
        """
        import asyncio

        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        timeout = aiohttp.ClientTimeout(total=15.0)  # 15 second timeout for photo

        # Truncate caption to Telegram limit (1024 chars)
        caption_truncated = self._truncate(caption, 1024)

        payload = {
            "chat_id": self.chat_id,
            "photo": photo_url,
            "caption": caption_truncated,
        }

        # Retry loop with exponential backoff
        for attempt in range(max_retries):
            try:
                async with (
                    aiohttp.ClientSession(timeout=timeout) as session,
                    session.post(url, json=payload) as response,
                ):
                    if response.status == 200:
                        logger.info("Manager notification with photo sent successfully")
                        return True

                    resp_text = await response.text()

                    # Retry on 5xx errors or rate limits
                    if (response.status >= 500 or response.status == 429) and attempt < max_retries - 1:
                        backoff = min(0.5 * (2 ** attempt), 2.0)
                        logger.warning(
                            "Telegram photo API error %d, retrying in %.1fs (attempt %d/%d)",
                            response.status,
                            backoff,
                            attempt + 1,
                            max_retries,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    logger.error(
                        "Failed to send photo notification: %s %s",
                        response.status,
                        resp_text[:200],
                    )
                    # Fallback to text-only message
                    return await self._send_telegram_message(caption_truncated)

            except TimeoutError:
                if attempt < max_retries - 1:
                    backoff = min(0.5 * (2 ** attempt), 2.0)
                    logger.warning(
                        "Telegram photo request timeout, retrying in %.1fs (attempt %d/%d)",
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Telegram photo request timeout after %d attempts", max_retries)
                # Fallback to text-only message
                return await self._send_telegram_message(caption_truncated)

            except Exception as e:
                if attempt < max_retries - 1:
                    backoff = min(0.5 * (2 ** attempt), 2.0)
                    logger.warning(
                        "Telegram photo notification error, retrying in %.1fs (attempt %d/%d): %s",
                        backoff,
                        attempt + 1,
                        max_retries,
                        str(e)[:100],
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Photo notification error after %d attempts: %s", max_retries, e)
                # Fallback to text-only message
                return await self._send_telegram_message(caption_truncated)

        # Final fallback
        return await self._send_telegram_message(caption_truncated)

    async def _send_telegram_message(self, text: str, max_retries: int = 3) -> bool:
        """
        Send raw message to Telegram with retry and backoff.
        
        Args:
            text: Message text to send
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if sent successfully, False otherwise
        """
        import asyncio

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        timeout = aiohttp.ClientTimeout(total=10.0)  # 10 second timeout

        # Try with Markdown first, fallback to plain text if parsing fails
        for parse_mode in ["Markdown", None]:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            # Retry loop with exponential backoff
            for attempt in range(max_retries):
                try:
                    async with (
                        aiohttp.ClientSession(timeout=timeout) as session,
                        session.post(url, json=payload) as response,
                    ):
                        if response.status == 200:
                            logger.info("Manager notification sent successfully")
                            return True

                        # If Markdown parsing failed, try without it
                        resp_text = await response.text()
                        if parse_mode == "Markdown" and "parse entities" in resp_text:
                            logger.warning("Markdown parsing failed, retrying without parse_mode")
                            break  # Break to try without parse_mode

                        # Retry on 5xx errors or rate limits
                        if response.status >= 500 or response.status == 429:
                            if attempt < max_retries - 1:
                                backoff = min(0.5 * (2 ** attempt), 2.0)  # Exponential backoff, max 2s
                                logger.warning(
                                    "Telegram API error %d, retrying in %.1fs (attempt %d/%d)",
                                    response.status,
                                    backoff,
                                    attempt + 1,
                                    max_retries,
                                )
                                await asyncio.sleep(backoff)
                                continue

                        logger.error(
                            "Failed to send notification: %s %s",
                            response.status,
                            resp_text[:200],
                        )
                        return False

                except TimeoutError:
                    if attempt < max_retries - 1:
                        backoff = min(0.5 * (2 ** attempt), 2.0)
                        logger.warning(
                            "Telegram request timeout, retrying in %.1fs (attempt %d/%d)",
                            backoff,
                            attempt + 1,
                            max_retries,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    logger.error("Telegram request timeout after %d attempts", max_retries)
                    return False

                except Exception as e:
                    if attempt < max_retries - 1:
                        backoff = min(0.5 * (2 ** attempt), 2.0)
                        logger.warning(
                            "Telegram notification error, retrying in %.1fs (attempt %d/%d): %s",
                            backoff,
                            attempt + 1,
                            max_retries,
                            str(e)[:100],
                        )
                        await asyncio.sleep(backoff)
                        continue
                    logger.error("Telegram notification error after %d attempts: %s", max_retries, e)
                    return False

        return False
