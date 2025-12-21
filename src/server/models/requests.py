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


class ApiV1MessageRequest(BaseModel):
    """Request model for /api/v1/messages endpoint.

    Supports multiple formats:
    - ManyChat External Request: {type, clientId, message, image_url}
    - n8n format: {sessionId, name, message} where message may contain image URL
    """

    type: str = Field(default="instagram")
    message: str = Field(default="", validation_alias=AliasChoices("message", "messages"))
    client_id: str = Field(
        validation_alias=AliasChoices("clientId", "client_id", "sessionId", "session_id"),
        serialization_alias="clientId",
    )
    client_name: str = Field(
        default="",
        validation_alias=AliasChoices("clientName", "client_name", "name"),
        serialization_alias="clientName",
    )
    username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("username", "userName", "user_name"),
        serialization_alias="username",
    )
    image_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "image_url",
            "imageUrl",
            "photo_url",
            "photoUrl",
            "image",
            "photo",
        ),
        serialization_alias="image_url",
    )

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")

    @model_validator(mode="after")
    def extract_image_from_message(self) -> ApiV1MessageRequest:
        """Extract image URL from message text if not provided separately.

        This handles the n8n format where message field contains the image URL.
        Also strips ManyChat/n8n prefix '.;' from messages.
        """
        msg = (self.message or "").strip()
        img_url = self.image_url

        # Strip ManyChat/n8n prefix '.;' (can appear multiple times)
        while msg.startswith(".;"):
            msg = msg[2:].lstrip()

        # Extract image URL from message text if not provided separately
        if not img_url and msg:
            match = _IMAGE_URL_PATTERN.search(msg)
            if match:
                img_url = match.group(0)
                logger.info("[API_V1] 📷 Extracted image URL from message: %s", img_url[:60])

        # Remove embedded image URL from message text
        if img_url and msg:
            msg = msg.replace(img_url, "").strip()
            # Strip prefix again in case it was before the URL
            while msg.startswith(".;"):
                msg = msg[2:].lstrip()

        if not msg and not img_url:
            raise ValueError("Either message or image_url is required")

        # Use object.__setattr__ for Pydantic v2 compatibility
        object.__setattr__(self, "message", msg)
        object.__setattr__(self, "image_url", img_url)
        return self


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
