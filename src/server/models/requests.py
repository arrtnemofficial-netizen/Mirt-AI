"""Request models for MIRT AI server.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging
import re

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

# Regex to detect image URLs in message text
# Supports:
# - Direct image URLs (.jpg, .png, etc.)
# - Instagram CDN: cdn.instagram.com, fbcdn, scontent
# - Instagram DM images: lookaside.fbsbx.com/ig_messaging_cdn
_IMAGE_URL_PATTERN = re.compile(
    r"(https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp|svg)|"
    r"https?://(?:cdn\.)?(?:instagram|fbcdn|scontent|lookaside\.fbsbx)[^\s]+)",
    re.IGNORECASE,
)


class SitniksUpdateRequest(BaseModel):
    """Request for updating Sitniks chat status from external systems."""

    stage: str = Field(description="Stage: first_touch, give_requisites, escalation")
    user_id: str = Field(
        description="MIRT user/session ID",
        validation_alias=AliasChoices(
            "user_id", "userId", "session_id", "sessionId", "client_id", "clientId"
        ),
    )
    instagram_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("instagram_username", "instagramUsername", "ig_username"),
    )
    telegram_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("telegram_username", "telegramUsername", "tg_username"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
