"""Request models for MIRT AI server.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging
import re

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


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
