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
        default="gpt-5.1", description="Identifier of the primary model used for reasoning."
    )
    OPENAI_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="API key for OpenAI GPT-5.1 and embeddings."
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

    MEDIA_PROXY_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable media proxy endpoint for serving external images from this service domain (helps Instagram/ManyChat image delivery)."
        ),
    )
    MEDIA_PROXY_ALLOWED_HOSTS: str = Field(
        default="cdn.sitniks.com",
        description="Comma-separated allowlist of hosts that /media/proxy is allowed to fetch.",
    )
    MEDIA_PROXY_TOKEN: str = Field(
        default="",
        description=(
            "Optional token for /media/proxy. If set, requests must include ?token=... (recommended to prevent open proxy abuse)."
        ),
    )

    # Manager Notification Bot
    MANAGER_BOT_TOKEN: SecretStr = Field(
        default=SecretStr(""), description="Token for internal manager notification bot."
    )
    MANAGER_CHAT_ID: str = Field(
        default="", description="Chat ID to send manager notifications to."
    )

    # ManyChat Integration
    MANYCHAT_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="ManyChat API key for full API access (sending messages, tags, fields).",
    )
    MANYCHAT_API_URL: str = Field(
        default="https://api.manychat.com",
        description="ManyChat API base URL.",
    )
    MANYCHAT_VERIFY_TOKEN: str = Field(
        default="", description="Shared token to validate ManyChat webhook calls."
    )
    MANYCHAT_PAGE_ID: str = Field(
        default="", description="Optional page/app identifier for routing incoming ManyChat events."
    )
    MANYCHAT_PUSH_MODE: bool = Field(
        default=True,
        description="Use async push mode (recommended). If False, uses sync response mode.",
    )

    MANYCHAT_USE_CELERY: bool = Field(
        default=False,
        description=(
            "If True and CELERY_ENABLED is also True, ManyChat incoming messages are processed via Celery tasks. "
            "If False, ManyChat uses FastAPI BackgroundTasks even when Celery is enabled (recommended when Celery is only for summarize/followups)."
        ),
    )

    MANYCHAT_IMAGE_PROXY_ENABLED: bool = Field(
        default=False,
        description=(
            "If True, image messages sent to ManyChat will be rewritten to use /media/proxy on this service (requires MEDIA_PROXY_ENABLED and HTTPS PUBLIC_BASE_URL)."
        ),
    )

    MANYCHAT_DEBOUNCE_SECONDS: float = Field(
        default=1.0,
        description="Debounce window (seconds) for aggregating rapid ManyChat messages.",
    )

    MANYCHAT_FALLBACK_AFTER_SECONDS: float = Field(
        default=10.0,
        description=(
            "If processing is still running after this many seconds, send a short interim message to the user."
        ),
    )

    MANYCHAT_INTERIM_TEXT: str = Field(
        default="Секунду, уточняю по наявності та деталях.",
        description="Short interim message for text-only processing when response is taking longer than expected.",
    )

    MANYCHAT_INTERIM_TEXT_WITH_IMAGE: str = Field(
        default="Дякую, бачу фото. Зараз перегляну та відповім.",
        description="Short interim message for image processing when response is taking longer than expected.",
    )

    # REMOVED: VISION_VIBE_TEXT_ANNA - now using universal snippet loader from snippets.md
    # All product-specific presentation texts are loaded dynamically from data/prompts/system/snippets.md

    MANYCHAT_TEXT_TIME_BUDGET_SECONDS: float = Field(
        default=22.0,
        description="Max processing time budget for text-only messages (seconds) before timeout fallback.",
    )

    MANYCHAT_VISION_TIME_BUDGET_SECONDS: float = Field(
        default=55.0,
        description="Max processing time budget for messages with images (seconds) before timeout fallback. Vision can take 20-30s.",
    )

    MANYCHAT_SAFE_MODE_INSTAGRAM: bool = Field(
        default=True,
        description=(
            "Enable strict safe mode for Instagram ManyChat sendContent: disables quick replies and restricts actions."
        ),
    )
    MANYCHAT_INSTAGRAM_DISABLE_ACTIONS: bool = Field(
        default=True,
        description=(
            "Disable ALL actions (fields/tags) for Instagram sendContent to maximize delivery reliability."
        ),
    )
    MANYCHAT_INSTAGRAM_ALLOWED_FIELDS: str = Field(
        default="ai_state,ai_intent",
        description=(
            "Comma-separated allowlist of Custom Fields allowed for Instagram when actions are enabled."
        ),
    )
    MANYCHAT_INSTAGRAM_SPLIT_SEND: bool = Field(
        default=True,
        description=(
            "Send each message bubble as a separate Instagram sendContent call with an inter-bubble delay."
        ),
    )
    MANYCHAT_INSTAGRAM_BUBBLE_DELAY_SECONDS: float = Field(
        default=5.0,
        description=(
            "Delay in seconds between Instagram bubbles when MANYCHAT_INSTAGRAM_SPLIT_SEND is enabled."
        ),
    )

    SUPABASE_URL: str = Field(
        default="", description="Supabase project URL for session persistence."
    )
    SUPABASE_API_KEY: SecretStr = Field(
        default=SecretStr(""), description="Service or anon key for Supabase client."
    )
    DATABASE_URL: str = Field(
        default="",
        description="Primary Postgres connection string for LangGraph checkpointer (falls back to SUPABASE_* when empty).",
    )
    SUPABASE_TABLE: str = Field(
        default="agent_sessions", description="Table name storing chat session state JSON."
    )
    SUPABASE_MESSAGES_TABLE: str = Field(
        default="messages",  # Was: mirt_messages (dropped in migration)
        description="Table storing raw chat messages (session-scoped).",
    )
    SUPABASE_USERS_TABLE: str = Field(
        default="users",  # Was: mirt_users (dropped, profiles in mirt_profiles)
        description="Table storing user profiles and summaries.",
    )
    # RAG tables removed - using Embedded Catalog in prompt
    # SUPABASE_CATALOG_TABLE, SUPABASE_EMBEDDINGS_TABLE, SUPABASE_MATCH_RPC - DELETED
    SUMMARY_RETENTION_DAYS: int = Field(
        default=3,
        description="Days after which conversations are summarized and pruned.",
    )

    DISABLE_CODE_STATE_PROMPTS_FALLBACK: bool = Field(
        default=False,
        description=(
            "If True, state prompts must be loaded from data/prompts/states/*.md; "
            "code fallback prompts are not allowed."
        ),
    )
    FOLLOWUP_DELAYS_HOURS: str = Field(
        default="24,72",
        description=(
            "Comma-separated list of hour offsets for proactive follow-ups "
            "(e.g. '24,72' sends after 24h and 72h of inactivity)."
        ),
    )

    # Snitkix CRM integration
    SNITKIX_API_URL: str = Field(default="", description="Snitkix CRM API base URL.")
    SNITKIX_API_KEY: SecretStr = Field(default=SecretStr(""), description="Snitkix CRM API key.")
    SITNIKS_AI_MANAGER_NAME: str = Field(
        default="Павло",
        description="Name of AI manager in Sitniks CRM (for first touch assignment).",
    )
    SITNIKS_HUMAN_MANAGER_ID: int | None = Field(
        default=None,
        description="Explicit manager ID for escalation. If None, picks first non-AI manager.",
    )

    # Celery / Redis configuration
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for Celery broker and result backend.",
    )
    CELERY_ENABLED: bool = Field(
        default=False,
        description="Enable Celery background tasks (requires Redis).",
    )
    CELERY_RESULT_TIMEOUT: int = Field(
        default=25,
        description="Seconds to wait for worker result when synchronous response is required.",
    )
    CELERY_EAGER: bool = Field(
        default=False,
        description="Run Celery tasks synchronously (for testing). Set via CELERY_EAGER env var.",
    )
    CELERY_CONCURRENCY: int = Field(
        default=4,
        description="Number of concurrent worker processes.",
    )
    CELERY_MAX_TASKS_PER_CHILD: int = Field(
        default=100,
        description="Max tasks per worker before restart (prevents memory leaks).",
    )

    # =========================================================================
    # MONITORING
    # =========================================================================
    SENTRY_DSN: str = Field(
        default="",
        description="Sentry DSN for error tracking. Leave empty to disable.",
    )
    SENTRY_ENVIRONMENT: str = Field(
        default="development",
        description="Sentry environment (development, staging, production).",
    )
    SENTRY_TRACES_SAMPLE_RATE: float = Field(
        default=0.1,
        description="Sentry traces sample rate (0.0-1.0).",
    )

    # =========================================================================
    # LLM CONFIGURATION (Parameterized)
    # =========================================================================
    # =========================================================================
    # LLM CONFIGURATION (Parameterized)
    # =========================================================================
    LLM_PROVIDER: str = Field(
        default="openai",
        description="LLM provider: openrouter, openai, google",
    )
    LLM_MODEL_GROK: str = Field(
        default="x-ai/grok-beta",
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
    LLM_MODEL_VISION: str = Field(
        default="gpt-5.1",
        description="Vision-capable model for photo analysis (must support multimodal)",
    )
    LLM_REASONING_EFFORT: str = Field(
        default="medium",
        description="Reasoning effort for reasoning models (none, low, medium, high). Medium recommended for vision.",
    )
    VISION_CONFIDENCE_THRESHOLD: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum confidence threshold for vision identification. "
            "If confidence < threshold, vision will request clarification or escalate. "
            "Default 0.5 (50%) means half-confident results require user confirmation."
        ),
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
    # FEATURE FLAGS
    # =========================================================================
    DEBUG_TRACE_LOGS: bool = Field(
        default=False,
        description="Enable pretty debug trace logs (request/routing/node entry/exit) for ManyChat testing.",
    )
    USE_OFFER_DELIBERATION: bool = Field(
        default=True,
        description="Enable Multi-Role Deliberation for STATE_4_OFFER (Customer/Business/Quality views)",
    )
    DELIBERATION_MIN_CONFIDENCE: float = Field(
        default=0.6,
        description="Minimum confidence for offer. Below this → fallback message",
    )

    # =========================================================================
    # LANGGRAPH CHECKPOINTER CONFIG
    # =========================================================================
    LANGGRAPH_CHECKPOINTER: str = Field(
        default="auto",
        description=(
            "Backend for LangGraph checkpointer: 'auto', 'memory', 'postgres', 'redis'. "
            "Use 'memory' for local Telegram polling if Supabase/Postgres is unstable."
        ),
    )
    CHECKPOINTER_WARMUP: bool = Field(
        default=True,
        description="Warm up checkpointer pool during startup.",
    )
    CHECKPOINTER_WARMUP_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        ge=0.0,
        description="Timeout for checkpointer warmup preflight.",
    )
    CHECKPOINTER_POOL_MIN_SIZE: int = Field(
        default=1,
        ge=0,
        description="Minimum size for checkpointer connection pool.",
    )
    CHECKPOINTER_POOL_MAX_SIZE: int = Field(
        default=5,
        ge=1,
        description="Maximum size for checkpointer connection pool.",
    )
    CHECKPOINTER_POOL_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        ge=0.0,
        description="Pool acquisition timeout in seconds.",
    )
    CHECKPOINTER_POOL_MAX_IDLE_SECONDS: float = Field(
        default=120.0,
        ge=0.0,
        description="Close idle connections after this many seconds.",
    )
    CHECKPOINTER_CONNECT_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        ge=0.0,
        description="Connect timeout for Postgres pool connections.",
    )
    CHECKPOINTER_STATEMENT_TIMEOUT_MS: int = Field(
        default=8000,
        ge=0,
        description="Postgres statement_timeout for checkpointer queries.",
    )
    CHECKPOINTER_LOCK_TIMEOUT_MS: int = Field(
        default=2000,
        ge=0,
        description="Postgres lock_timeout for checkpointer queries.",
    )
    CHECKPOINTER_SLOW_LOG_SECONDS: float = Field(
        default=1.0,
        ge=0.0,
        description="Log checkpointer operations slower than this threshold.",
    )
    CHECKPOINTER_MAX_MESSAGES: int = Field(
        default=200,
        ge=0,
        description="Max messages to keep in checkpoint payload (0 disables trimming).",
    )
    CHECKPOINTER_MAX_MESSAGE_CHARS: int = Field(
        default=4000,
        ge=0,
        description="Max characters per message to store in checkpoint payload.",
    )
    CHECKPOINTER_DROP_BASE64: bool = Field(
        default=True,
        description="Strip base64 image payloads from checkpoint state.",
    )

    # =========================================================================
    # INTEGRATION FEATURE FLAGS
    # =========================================================================
    # Use these to disable heavy integrations for lightweight Telegram polling

    ENABLE_PAYMENT_HITL: bool = Field(
        default=False,
        description=(
            "Enable Human-in-the-Loop for payment approval. "
            "Requires webhook-based flow (ManyChat). "
            "Disable for Telegram polling to avoid graph interrupts."
        ),
    )

    ENABLE_CRM_INTEGRATION: bool = Field(
        default=False,
        description=(
            "Enable Sitniks CRM integration (order creation, status updates). "
            "Disable for local testing or when CRM is unavailable."
        ),
    )

    MANYCHAT_PUSH_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        description="Max retries for transient ManyChat push failures.",
    )
    MANYCHAT_PUSH_RETRY_BASE_DELAY_SECONDS: float = Field(
        default=0.5,
        ge=0.0,
        description="Base delay for ManyChat push retry backoff.",
    )
    MANYCHAT_PUSH_RETRY_MAX_DELAY_SECONDS: float = Field(
        default=3.0,
        ge=0.0,
        description="Maximum delay between ManyChat push retries.",
    )

    # =========================================================================
    # PERFORMANCE / LOAD HANDLING
    # =========================================================================

    LLM_MAX_HISTORY_MESSAGES: int = Field(
        default=20,
        description=(
            "Maximum number of messages to send to LLM. "
            "Older messages are trimmed to prevent context overflow. "
            "Set to 0 to disable trimming."
        ),
    )

    DEBOUNCER_DELAY_SECONDS: float = Field(
        default=2.5,
        description="Delay before processing aggregated messages in Telegram",
    )

    # =========================================================================
    # OBSERVABILITY
    # =========================================================================
    ENABLE_OBSERVABILITY: bool = Field(
        default=True,
        description="Enable detailed logging with tags (state/intent/tool)",
    )
    # NOTE: Legacy feature flags removed (USE_GRAPH_V2, USE_TOOL_PLANNER, etc.)
    # - LangGraph v2 is now the only architecture
    # - PydanticAI handles tool planning automatically
    # - Validation is done by LangGraph nodes

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
