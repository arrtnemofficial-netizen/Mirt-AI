"""Sitniks CRM Chat Service.

Handles chat status updates and manager assignments.
Requires paid Sitniks plan for API access.

Statuses flow:
- "????? ? ??????" ? first touch, AI starts handling
- "?????????? ???????" ? payment requisites sent
- "AI ?????" ? escalation, needs human manager
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.conf.config import settings
# PostgreSQL only - no Supabase dependency


logger = logging.getLogger(__name__)


# Sitniks status names (from user's CRM)
class SitniksStatus:
    FIRST_TOUCH = "????? ? ??????"
    INVOICE_SENT = "?????????? ???????"
    AI_ATTENTION = "AI ?????"
    NEW = "???? ??????"
    PAID = "????????"
    ORDER_FORMED = "????????? ??????????"


# Manager configuration loaded from settings


class SitniksChatService:
    """Service for managing Sitniks CRM chat statuses."""

    def __init__(self):
        self.api_url = getattr(settings, "SNITKIX_API_URL", "").rstrip("/")
        # SNITKIX_API_KEY is SecretStr, need to extract value
        api_key_secret = getattr(settings, "SNITKIX_API_KEY", None)
        if api_key_secret and hasattr(api_key_secret, "get_secret_value"):
            self.api_key = api_key_secret.get_secret_value()
        else:
            self.api_key = str(api_key_secret) if api_key_secret else ""
        # PostgreSQL only - no Supabase
        self._managers_cache: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and self.api_key)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def find_chat_by_username(
        self,
        instagram_username: str | None = None,
        telegram_username: str | None = None,
        lookback_minutes: int = 5,
    ) -> str | None:
        """Find Sitniks chat ID by username.

        Searches recent chats (last N minutes) and matches by userNickName.

        Args:
            instagram_username: Instagram @username (without @)
            telegram_username: Telegram @username (without @)
            lookback_minutes: How far back to search for chats

        Returns:
            Sitniks chat ID if found, None otherwise
        """
        if not self.enabled:
            logger.warning("[SITNIKS] Chat service not configured")
            return None

        username = instagram_username or telegram_username
        if not username:
            logger.warning("[SITNIKS] No username provided for chat lookup")
            return None

        # Remove @ if present
        username = username.lstrip("@").lower()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Calculate time range
                end_date = datetime.now(UTC)
                start_date = end_date - timedelta(minutes=lookback_minutes)

                params = {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "limit": 50,
                }

                response = await client.get(
                    f"{self.api_url}/open-api/chats",
                    headers=self._get_headers(),
                    params=params,
                )

                if response.status_code == 200:
                    data = response.json()
                    chats = data.get("data", [])

                    for chat in chats:
                        chat_username = (chat.get("userNickName") or "").lower()
                        if chat_username == username:
                            chat_id = chat.get("id")
                            logger.info(
                                "[SITNIKS] Found chat %s for username %s",
                                chat_id,
                                username,
                            )
                            return chat_id

                    logger.info(
                        "[SITNIKS] No chat found for username %s in last %d minutes",
                        username,
                        lookback_minutes,
                    )
                    return None

                elif response.status_code == 403:
                    logger.error("[SITNIKS] API access forbidden (403). Need paid plan.")
                    return None
                else:
                    logger.error(
                        "[SITNIKS] Failed to fetch chats: %d %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return None

        except Exception as e:
            logger.exception("[SITNIKS] Error finding chat: %s", e)
            return None

    async def update_chat_status(
        self,
        chat_id: str,
        status: str,
    ) -> bool:
        """Update chat status in Sitniks CRM.

        Args:
            chat_id: Sitniks chat ID
            status: New status name (e.g. "Взято в роботу")

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.warning("[SITNIKS] Chat service not configured")
            return False

        if not chat_id:
            logger.warning("[SITNIKS] No chat_id provided for status update")
            return False

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.patch(
                    f"{self.api_url}/open-api/chats/{chat_id}/status",
                    headers=self._get_headers(),
                    json={"status": status},
                )

                if response.status_code == 200:
                    logger.info(
                        "[SITNIKS] Updated chat %s status to '%s'",
                        chat_id,
                        status,
                    )
                    return True
                elif response.status_code == 403:
                    logger.error("[SITNIKS] API access forbidden (403)")
                    return False
                else:
                    logger.error(
                        "[SITNIKS] Failed to update status: %d %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return False

        except Exception as e:
            logger.exception("[SITNIKS] Error updating status: %s", e)
            return False

    async def get_managers(self) -> list[dict[str, Any]]:
        """Fetch list of managers from Sitniks CRM."""
        if not self.enabled:
            return []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.api_url}/open-api/managers",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    data = response.json()
                    managers = data.get("data", [])

                    # Cache managers by name
                    for m in managers:
                        user = m.get("user", {})
                        name = user.get("fullname", "")
                        if name:
                            self._managers_cache[name.lower()] = m.get("id")

                    return managers
                else:
                    logger.error(
                        "[SITNIKS] Failed to fetch managers: %d",
                        response.status_code,
                    )
                    return []

        except Exception as e:
            logger.exception("[SITNIKS] Error fetching managers: %s", e)
            return []

    async def get_manager_id_by_name(self, name: str) -> int | None:
        """Get manager ID by name (case-insensitive)."""
        name_lower = name.lower()

        if name_lower in self._managers_cache:
            return self._managers_cache[name_lower]

        # Fetch managers if cache is empty
        await self.get_managers()

        return self._managers_cache.get(name_lower)

    async def assign_manager(
        self,
        chat_id: str,
        manager_id: int,
    ) -> bool:
        """Assign a manager to a chat.

        Note: The exact API endpoint for this may vary.
        Check Sitniks documentation for the correct endpoint.
        """
        if not self.enabled or not chat_id:
            return False

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Note: This endpoint path is assumed based on common patterns
                # Actual endpoint may differ - check Sitniks docs
                response = await client.patch(
                    f"{self.api_url}/open-api/chats/{chat_id}",
                    headers=self._get_headers(),
                    json={"assignedManagerId": manager_id},
                )

                if response.status_code == 200:
                    logger.info(
                        "[SITNIKS] Assigned manager %d to chat %s",
                        manager_id,
                        chat_id,
                    )
                    return True
                else:
                    logger.error(
                        "[SITNIKS] Failed to assign manager: %d %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return False

        except Exception as e:
            logger.exception("[SITNIKS] Error assigning manager: %s", e)
            return False

    async def handle_first_touch(
        self,
        user_id: str,
        instagram_username: str | None = None,
        telegram_username: str | None = None,
    ) -> dict[str, Any]:
        """Handle first touch: find chat, set status, assign AI manager.

        This should be called BEFORE sending the first response to a new user.

        Args:
            user_id: MIRT user ID (session_id)
            instagram_username: Instagram username
            telegram_username: Telegram username

        Returns:
            Result dict with chat_id and success status
        """
        result = {
            "success": False,
            "chat_id": None,
            "status_set": False,
            "manager_assigned": False,
            "error": None,
        }

        # 1. Find chat by username
        chat_id = await self.find_chat_by_username(
            instagram_username=instagram_username,
            telegram_username=telegram_username,
            lookback_minutes=5,
        )

        if not chat_id:
            result["error"] = "Chat not found in Sitniks"
            return result

        result["chat_id"] = chat_id

        # 2. Save mapping to Supabase
        await self._save_chat_mapping(
            user_id=user_id,
            chat_id=chat_id,
            instagram_username=instagram_username,
            telegram_username=telegram_username,
        )

        # 3. Set status to "Взято в роботу"
        status_ok = await self.update_chat_status(
            chat_id=chat_id,
            status=SitniksStatus.FIRST_TOUCH,
        )
        result["status_set"] = status_ok

        # 4. Assign AI manager
        ai_manager_name = settings.SITNIKS_AI_MANAGER_NAME
        ai_manager_id = await self.get_manager_id_by_name(ai_manager_name)
        if ai_manager_id:
            manager_ok = await self.assign_manager(chat_id, ai_manager_id)
            result["manager_assigned"] = manager_ok
        else:
            logger.warning(
                "[SITNIKS] AI manager '%s' not found in CRM",
                ai_manager_name,
            )

        result["success"] = status_ok
        return result

    async def handle_invoice_sent(self, user_id: str) -> bool:
        """Set status to "Виставлено рахунок" when requisites are sent."""
        chat_id = await self._get_chat_id_for_user(user_id)
        if not chat_id:
            logger.warning("[SITNIKS] No chat_id found for user %s", user_id)
            return False

        return await self.update_chat_status(chat_id, SitniksStatus.INVOICE_SENT)

    async def handle_escalation(self, user_id: str) -> dict[str, Any]:
        """Handle escalation: set AI Attention status, assign to human manager.

        Returns:
            Result with success status and manager assignment info
        """
        result = {
            "success": False,
            "chat_id": None,
            "status_set": False,
            "manager_assigned": False,
        }

        chat_id = await self._get_chat_id_for_user(user_id)
        if not chat_id:
            logger.warning("[SITNIKS] No chat_id found for user %s", user_id)
            return result

        result["chat_id"] = chat_id

        # 1. Set status to "AI Увага"
        status_ok = await self.update_chat_status(chat_id, SitniksStatus.AI_ATTENTION)
        result["status_set"] = status_ok

        # 2. Assign to a human manager
        human_manager_id = settings.SITNIKS_HUMAN_MANAGER_ID

        if human_manager_id:
            # Use configured manager ID
            manager_ok = await self.assign_manager(chat_id, human_manager_id)
            result["manager_assigned"] = manager_ok
        else:
            # Fallback: pick first non-AI manager from API
            managers = await self.get_managers()
            ai_name = settings.SITNIKS_AI_MANAGER_NAME.lower()
            for m in managers:
                user = m.get("user", {})
                name = user.get("fullname", "").lower()
                if name != ai_name:
                    manager_ok = await self.assign_manager(chat_id, m["id"])
                    result["manager_assigned"] = manager_ok
                    break

        result["success"] = status_ok
        return result

    async def _save_chat_mapping(
        self,
        user_id: str,
        chat_id: str,
        instagram_username: str | None,
        telegram_username: str | None,
    ) -> None:
        """Save user-to-chat mapping in PostgreSQL."""
        try:
            import psycopg
            from src.services.postgres_pool import get_postgres_url
            
            try:
                postgres_url = get_postgres_url()
            except ValueError:
                return
            with psycopg.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO sitniks_chat_mappings 
                        (user_id, sitniks_chat_id, instagram_username, telegram_username, first_touch_at, updated_at)
                        VALUES (%s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (user_id) 
                        DO UPDATE SET
                            sitniks_chat_id = EXCLUDED.sitniks_chat_id,
                            instagram_username = EXCLUDED.instagram_username,
                            telegram_username = EXCLUDED.telegram_username,
                            updated_at = NOW()
                        """,
                        (user_id, chat_id, instagram_username, telegram_username),
                    )
                    conn.commit()
        except Exception as e:
            logger.error("[SITNIKS] Failed to save chat mapping: %s", e)

    async def _get_chat_id_for_user(self, user_id: str) -> str | None:
        """Get Sitniks chat ID for a MIRT user from PostgreSQL."""
        try:
            import psycopg
            from src.services.postgres_pool import get_postgres_url
            
            try:
                postgres_url = get_postgres_url()
            except ValueError:
                return None
            with psycopg.connect(postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT sitniks_chat_id
                        FROM sitniks_chat_mappings
                        WHERE user_id = %s
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
            
            if row:
                return row[0]
            return None
        except Exception:
            return None


# Singleton
_chat_service: SitniksChatService | None = None


def get_sitniks_chat_service() -> SitniksChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = SitniksChatService()
    return _chat_service
