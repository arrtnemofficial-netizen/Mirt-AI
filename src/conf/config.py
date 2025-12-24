"""Configuration for AI agent services.

Reads environment variables for API access and runtime tuning.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration loaded from environment."""

    AI_MODEL: str = Field(
        default="gpt-5.1", description="Identifier of the primary model used for reasoning (OpenAI GPT-5.1 only)."
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
    MANYCHAT_VERIFY_TOKEN: str = Field(
        default="", description="Shared token to validate ManyChat webhook calls."
    )
    MANYCHAT_PAGE_ID: str = Field(
        default="", description="Optional page/app identifier for routing incoming ManyChat events."
    )
    MANYCHAT_PUSH_MODE: bool = Field(
        default=True,
        description=(
            "Enable push mode for ManyChat webhooks. "
            "When true: returns 202 immediately and processes async (recommended). "
            "When false: waits for AI response (legacy, may timeout on long operations)."
        ),
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
        default="messages",
        description="Table storing raw chat messages (session-scoped).",
    )
    SUPABASE_USERS_TABLE: str = Field(
        default="mirt_users",
        description="Table storing user profiles and summaries.",
    )
    # RAG tables removed - using Embedded Catalog in prompt
    # SUPABASE_CATALOG_TABLE, SUPABASE_EMBEDDINGS_TABLE, SUPABASE_MATCH_RPC - DELETED
    SUMMARY_RETENTION_DAYS: int = Field(
        default=3,
        description="Days after which conversations are summarized and pruned.",
    )
    FOLLOWUP_DELAYS_HOURS: str = Field(
        default="4,23",
        description=(
            "Comma-separated list of hour offsets for proactive follow-ups "
            "(e.g. '4,23' sends after 4h and 23h of inactivity)."
        ),
    )

    # Checkpoint compaction safeguards
    COMPACTION_ENABLED: bool = Field(
        default=True,
        description="Enable checkpoint payload compaction (disable for debugging).",
    )

    # Loop guard thresholds (conversation safety)
    LOOP_GUARD_WARNING_THRESHOLD: int = Field(
        default=5, gt=0, description="Warn when user/agent loop count reaches this threshold."
    )
    LOOP_GUARD_SOFT_RESET: int = Field(
        default=10, gt=0, description="Soft reset when loop count reaches this threshold."
    )
    LOOP_GUARD_ESCALATION: int = Field(
        default=20, gt=0, description="Escalate when loop count reaches this threshold."
    )

    @model_validator(mode="after")
    def _validate_loop_guard_thresholds(self) -> "Settings":
        if self.LOOP_GUARD_WARNING_THRESHOLD >= self.LOOP_GUARD_SOFT_RESET:
            raise ValueError("LOOP_GUARD_WARNING_THRESHOLD must be < LOOP_GUARD_SOFT_RESET")
        if self.LOOP_GUARD_SOFT_RESET > self.LOOP_GUARD_ESCALATION:
            raise ValueError("LOOP_GUARD_SOFT_RESET must be <= LOOP_GUARD_ESCALATION")
        return self

    # Snitkix CRM integration
    SNITKIX_API_URL: str = Field(default="", description="Snitkix CRM API base URL.")
    SNITKIX_API_KEY: SecretStr = Field(default=SecretStr(""), description="Snitkix CRM API key.")

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
        description="LLM provider: openai only (OpenRouter removed)",
    )
    LLM_MODEL_GPT: str = Field(
        default="gpt-5.1",
        description="OpenAI GPT model identifier (GPT-5.1 only)",
    )
    LLM_MODEL_GEMINI: str = Field(
        default="gemini-3-pro",
        description="Google Gemini model identifier",
    )
    LLM_REASONING_EFFORT: str = Field(
        default="low",
        description="Reasoning effort for reasoning models (none, low, medium, high).",
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
    # OBSERVABILITY
    # =========================================================================
    ENABLE_OBSERVABILITY: bool = Field(
        default=True,
        description="Enable detailed logging with tags (state/intent/tool)",
    )
    ENABLE_LEGACY_STATE_ALIASES: bool = Field(
        default=True,
        description=(
            "Allow legacy state aliases in normalize_state for backward compatibility. "
            "Legacy aliases map old state names (e.g., 'STATE0_INIT') to new enum values. "
            "See docs/quality/FEATURE_FLAGS_POLICY.md for migration plan."
        ),
    )
    DEBUG_TRACE_LOGS: bool = Field(
        default=False,
        description="Enable detailed trace logging for debugging.",
    )

    # =========================================================================
    # OFFER DELIBERATION / CONFIDENCE GATING
    # =========================================================================
    USE_OFFER_DELIBERATION: bool = Field(
        default=True,
        description="Enable offer deliberation gating (low confidence / price mismatch).",
    )
    DELIBERATION_MIN_CONFIDENCE: float = Field(
        default=0.8,
        description="Minimum acceptable offer deliberation confidence (0.0-1.0). Below => fallback.",
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
        """Return the active LLM model (OpenAI GPT-5.1 only)."""
        return self.LLM_MODEL_GPT

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


def validate_ssot_files() -> None:
    """Validate that all required SSOT (Single Source of Truth) files exist and are valid.
    
    FAIL-FAST: Raises RuntimeError if any critical SSOT file is missing or invalid.
    This ensures we never use stale hardcoded fallback data.
    
    Raises:
        RuntimeError: If any required SSOT file is missing or invalid.
    """
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    
    # Base path for data files
    base_path = Path(__file__).parent.parent.parent / "data"
    
    # Required SSOT files (critical for agent operation)
    required_files = {
        "size_guide.yaml": base_path / "prompts" / "system" / "size_guide.yaml",
    }
    
    errors: list[str] = []
    
    for file_name, file_path in required_files.items():
        if not file_path.exists():
            errors.append(
                f"CRITICAL: SSOT file missing: {file_path}. "
                f"This file is required for agent operation. "
                f"Ensure data/prompts/system/{file_name} exists in deployment."
            )
            continue
        
        # Validate size_guide.yaml structure
        if file_name == "size_guide.yaml":
            try:
                import yaml
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    errors.append(
                        f"CRITICAL: Invalid YAML structure in {file_path}. "
                        "Expected dict with 'size_mapping' and 'border_sizes' keys."
                    )
                elif not isinstance(data.get("size_mapping"), list) or not data.get("size_mapping"):
                    errors.append(
                        f"CRITICAL: Invalid 'size_mapping' in {file_path}. "
                        "Expected non-empty list of size range dictionaries."
                    )
                elif not isinstance(data.get("border_sizes"), dict):
                    errors.append(
                        f"CRITICAL: Invalid 'border_sizes' in {file_path}. "
                        "Expected dict mapping height (int) to size string."
                    )
            except yaml.YAMLError as e:
                errors.append(
                    f"CRITICAL: Failed to parse YAML in {file_path}: {e}. "
                    "Check file syntax and encoding (must be UTF-8)."
                )
            except Exception as e:
                errors.append(
                    f"CRITICAL: Failed to validate {file_path}: {e}."
                )
    
    if errors:
        error_msg = "SSOT file validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    logger.info("SSOT files validation passed")


def validate_required_settings(settings_instance: Settings | None = None) -> None:
    """Validate that all required environment variables are set.

    This is a legacy validation function. For comprehensive validation with
    format checks and structured errors, use preflight_validation module.

    Raises RuntimeError if critical settings are missing.

    Args:
        settings_instance: Settings instance to validate. If None, uses global settings.
    """
    import logging
    import os

    logger = logging.getLogger(__name__)

    if settings_instance is None:
        settings_instance = get_settings()

    errors: list[str] = []
    warnings: list[str] = []

    # Determine environment
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env in ("production", "prod", "staging") or (
        settings_instance.PUBLIC_BASE_URL != "http://localhost:8000"
    )

    # Critical settings (required in production)
    if is_production:
        if not settings_instance.OPENAI_API_KEY.get_secret_value():
            errors.append("OPENAI_API_KEY is required in production")

        if not settings_instance.SUPABASE_URL:
            errors.append("SUPABASE_URL is required in production")

        if not settings_instance.SUPABASE_API_KEY.get_secret_value():
            errors.append("SUPABASE_API_KEY is required in production")

    # Important settings (warnings in production)
    if is_production:
        if not settings_instance.MANYCHAT_API_KEY.get_secret_value():
            warnings.append("MANYCHAT_API_KEY not set (ManyChat integration disabled)")

        if not settings_instance.MANYCHAT_VERIFY_TOKEN:
            warnings.append("MANYCHAT_VERIFY_TOKEN not set (ManyChat webhook validation disabled)")

        if not settings_instance.REDIS_URL or settings_instance.REDIS_URL == "redis://localhost:6379/0":
            warnings.append("REDIS_URL not configured (using default, may not work in production)")

    # Log warnings
    for warning in warnings:
        logger.warning("Configuration warning: %s", warning)

    # Raise errors
    if errors:
        error_msg = "Critical configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Validate SSOT files (fail-fast for critical data files)
    validate_ssot_files()


settings = get_settings()
