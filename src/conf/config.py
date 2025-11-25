"""Configuration for AI agent services.

Reads environment variables for API access and runtime tuning.
"""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration loaded from environment."""

    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for OpenRouter-compatible endpoints.",
    )
    OPENROUTER_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="API key for OpenRouter/Grok 4.1 fast access."
    )
    AI_MODEL: str = Field(
        default="x-ai/grok-4.1-fast", description="Identifier of the model used for reasoning."
    )
    DEFAULT_SESSION_ID: str = Field(
        default="local-dev", description="Fallback session id for local runs."
    )

    TELEGRAM_BOT_TOKEN: SecretStr = Field(
        default=SecretStr(""), description="Bot token issued by BotFather."
    )
    TELEGRAM_WEBHOOK_PATH: str = Field(
        default="/webhooks/telegram", description="Path for Telegram webhook handler."
    )
    PUBLIC_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Publicly reachable base URL used for webhook registration.",
    )

    MANYCHAT_VERIFY_TOKEN: str = Field(
        default="", description="Shared token to validate ManyChat webhook calls."
    )
    MANYCHAT_PAGE_ID: str = Field(
        default="", description="Optional page/app identifier for routing incoming ManyChat events."
    )

    SUPABASE_URL: str = Field(
        default="", description="Supabase project URL for session persistence."
    )
    SUPABASE_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="Service or anon key for Supabase client."
    )
    SUPABASE_TABLE: str = Field(
        default="agent_sessions", description="Table name storing chat session state JSON."
    )
    SUPABASE_MESSAGES_TABLE: str = Field(
        default="messages", description="Table storing raw chat messages (session-scoped).",
    )
    SUPABASE_USERS_TABLE: str = Field(
        default="users", description="Table storing user profiles and summaries.",
    )
    SUPABASE_CATALOG_TABLE: str = Field(
        default="products", description="Table name with product catalog rows for RAG search.",
    )
    SUMMARY_RETENTION_DAYS: int = Field(
        default=3, description="Days after which conversations are summarized and pruned.",
    )
    FOLLOWUP_DELAYS_HOURS: str = Field(
        default="24,72",
        description=(
            "Comma-separated list of hour offsets for proactive follow-ups "
            "(e.g. '24,72' sends after 24h and 72h of inactivity)."
        ),
    )

    @property
    def followup_schedule_hours(self) -> list[int]:
        """Return parsed follow-up delays as a list of hour integers."""

        raw = [segment.strip() for segment in self.FOLLOWUP_DELAYS_HOURS.split(",")]
        hours: list[int] = []
        for segment in raw:
            if not segment:
                continue
            try:
                hours.append(int(segment))
            except ValueError:
                continue
        return [h for h in hours if h > 0]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()  # type: ignore[arg-type]


settings = get_settings()
