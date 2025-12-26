from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row

from src.services.memory.base import MemoryBase
from src.services.memory.constants import TABLE_PROFILES


logger = logging.getLogger(__name__)


class ProfilesMixin(MemoryBase):
    """Profile CRUD operations."""

    async def get_profile(self, user_id: str):
        if not self._enabled:
            return None

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"SELECT * FROM {TABLE_PROFILES} WHERE user_id = %s LIMIT 1",
                        (user_id,),
                    )
                    return cur.fetchone()

        try:
            row = await self._run_db(_query)
            if not row:
                return None
            return self._row_to_profile(row)
        except Exception as e:
            if "0 rows" in str(e).lower():
                return None
            logger.error("Failed to get profile for user %s: %s", user_id, e)
            return None

    async def get_or_create_profile(self, user_id: str):
        existing = await self.get_profile(user_id)
        if existing:
            return existing
        return await self.create_profile(user_id)

    async def create_profile(self, user_id: str):
        if not self._enabled:
            return self.models["UserProfile"](user_id=user_id)

        now = datetime.now(UTC).isoformat()
        data = {
            "user_id": user_id,
            "child_profile": {},
            "style_preferences": {},
            "logistics": {},
            "commerce": {},
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }

        def _query():
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {TABLE_PROFILES}
                        (user_id, child_profile, style_preferences, logistics, commerce,
                         created_at, updated_at, last_seen_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            data["user_id"],
                            data["child_profile"],
                            data["style_preferences"],
                            data["logistics"],
                            data["commerce"],
                            data["created_at"],
                            data["updated_at"],
                            data["last_seen_at"],
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return row

        try:
            row = await self._run_db(_query)
            if row:
                logger.info("Created profile for user %s", user_id)
                return self._row_to_profile(row)
            return self.models["UserProfile"](user_id=user_id)
        except Exception as e:
            logger.error("Failed to create profile for user %s: %s", user_id, e)
            return self.models["UserProfile"](user_id=user_id)

    async def update_profile(
        self,
        user_id: str,
        child_profile: dict | None = None,
        style_preferences: dict | None = None,
        logistics: dict | None = None,
        commerce: dict | None = None,
    ):
        if not self._enabled:
            return None

        try:
            current = await self.get_profile(user_id)
            if not current:
                current = await self.create_profile(user_id)

            updates: dict[str, Any] = {
                "updated_at": datetime.now(UTC).isoformat(),
                "last_seen_at": datetime.now(UTC).isoformat(),
            }

            if child_profile:
                merged = {**current.child_profile.model_dump(), **child_profile}
                updates["child_profile"] = merged

            if style_preferences:
                merged = {**current.style_preferences.model_dump(), **style_preferences}
                for key in [
                    "favorite_models",
                    "favorite_colors",
                    "avoided_colors",
                    "preferred_styles",
                    "fabric_preferences",
                ]:
                    if key in style_preferences and key in current.style_preferences.model_dump():
                        existing = current.style_preferences.model_dump().get(key, [])
                        new = style_preferences.get(key, [])
                        merged[key] = list(set(existing + new))
                updates["style_preferences"] = merged

            if logistics:
                merged = {**current.logistics.model_dump(), **logistics}
                updates["logistics"] = merged

            if commerce:
                merged = {**current.commerce.model_dump(), **commerce}
                updates["commerce"] = merged

            set_clause = ", ".join(f"{key} = %s" for key in updates.keys())
            values = list(updates.values()) + [user_id]

            def _query():
                with self._get_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            f"""
                            UPDATE {TABLE_PROFILES}
                            SET {set_clause}
                            WHERE user_id = %s
                            RETURNING *
                            """,
                            values,
                        )
                        row = cur.fetchone()
                    conn.commit()
                return row

            row = await self._run_db(_query)
            if row:
                logger.info("Updated profile for user %s", user_id)
                return self._row_to_profile(row)
            return current
        except Exception as e:
            logger.error("Failed to update profile for user %s: %s", user_id, e)
            return None

    async def touch_profile(self, user_id: str) -> None:
        if not self._enabled:
            return

        def _query():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {TABLE_PROFILES}
                        SET last_seen_at = %s
                        WHERE user_id = %s
                        """,
                        (datetime.now(UTC).isoformat(), user_id),
                    )
                conn.commit()

        try:
            await self._run_db(_query)
        except Exception as e:
            logger.warning("Failed to touch profile for user %s: %s", user_id, e)

    def _row_to_profile(self, row: dict):
        m = self.models
        return m["UserProfile"](
            user_id=row.get("user_id", ""),
            child_profile=m["ChildProfile"](**row.get("child_profile", {})),
            style_preferences=m["StylePreferences"](**row.get("style_preferences", {})),
            logistics=m["LogisticsInfo"](**row.get("logistics", {})),
            commerce=m["CommerceInfo"](**row.get("commerce", {})),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_seen_at=row.get("last_seen_at"),
            completeness_score=row.get("completeness_score", 0.0),
        )
