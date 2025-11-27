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
    OPENAI_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="API key for embedding generation."
    )
    # EMBEDDING_MODEL and EMBEDDING_DIM removed - RAG disabled, using Embedded Catalog
    DEFAULT_SESSION_ID: str = Field(
        default="", description="Fallback session id when none is provided in input metadata."
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
        default="mirt_messages", description="Table storing raw chat messages (session-scoped).",
    )
    SUPABASE_USERS_TABLE: str = Field(
        default="mirt_users", description="Table storing user profiles and summaries.",
    )
    # RAG tables removed - using Embedded Catalog in prompt
    # SUPABASE_CATALOG_TABLE, SUPABASE_EMBEDDINGS_TABLE, SUPABASE_MATCH_RPC - DELETED
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

    # Snitkix CRM integration
    SNITKIX_API_URL: str = Field(
        default="", description="Snitkix CRM API base URL."
    )
    SNITKIX_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="Snitkix CRM API key."
    )

    # =========================================================================
    # LLM CONFIGURATION (Parameterized)
    # =========================================================================
    LLM_PROVIDER: str = Field(
        default="openrouter",
        description="LLM provider: openrouter, openai, google",
    )
    LLM_MODEL_GROK: str = Field(
        default="x-ai/grok-4.1-fast",
        description="Grok model identifier for OpenRouter",
    )
    LLM_MODEL_GPT: str = Field(
        default="gpt-5.1",
        description="OpenAI GPT model identifier",
    )
    LLM_MODEL_GEMINI: str = Field(
        default="gemini-3-pro",
        description="Google Gemini model identifier",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.3,
        description="LLM temperature (0.0-1.0)",
    )
    LLM_MAX_TOKENS: int = Field(
        default=2048,
        description="Max tokens for LLM response",
    )
    PROMPT_TEMPLATE: str = Field(
        default="default",
        description="Prompt template to use: default, grok, gpt, gemini",
    )

    # =========================================================================
    # FEATURE FLAGS (for safe rollout)
    # =========================================================================
    USE_GRAPH_V2: bool = Field(
        default=True,
        description="Use multi-node LangGraph v2 (moderation → tools → agent → validation → state_transition)",
    )
    USE_TOOL_PLANNER: bool = Field(
        default=True,
        description="Pre-execute tools in code before calling LLM",
    )
    USE_PRODUCT_VALIDATION: bool = Field(
        default=True,
        description="Validate products (price > 0, photo_url) before sending",
    )
    USE_INPUT_VALIDATION: bool = Field(
        default=True,
        description="Validate and clamp input metadata to enums",
    )
    ENABLE_OBSERVABILITY: bool = Field(
        default=True,
        description="Enable detailed logging with tags (state/intent/tool)",
    )

    @property
    def snitkix_enabled(self) -> bool:
        """Check if Snitkix CRM is configured."""
        return bool(self.SNITKIX_API_URL and self.SNITKIX_API_KEY.get_secret_value())

    @property
    def active_llm_model(self) -> str:
        """Return the active LLM model based on provider."""
        if self.LLM_PROVIDER == "openai":
            return self.LLM_MODEL_GPT
        elif self.LLM_PROVIDER == "google":
            return self.LLM_MODEL_GEMINI
        else:
            return self.LLM_MODEL_GROK

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
