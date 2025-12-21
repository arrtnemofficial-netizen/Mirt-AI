from __future__ import annotations


def _resolve_settings(settings_override=None):
    if settings_override is not None:
        return settings_override
    from src.conf.config import settings as app_settings

    return app_settings


def get_llm_history_limit(settings_override=None) -> int:
    settings = _resolve_settings(settings_override)
    return int(getattr(settings, "LLM_MAX_HISTORY_MESSAGES", 20))


def get_state_message_limit(settings_override=None) -> int:
    settings = _resolve_settings(settings_override)
    return int(getattr(settings, "STATE_MAX_MESSAGES", 100))


def get_checkpoint_compaction(settings_override=None) -> tuple[int, int, bool]:
    settings = _resolve_settings(settings_override)
    max_messages = int(getattr(settings, "CHECKPOINTER_MAX_MESSAGES", 200))
    max_chars = int(getattr(settings, "CHECKPOINTER_MAX_MESSAGE_CHARS", 4000))
    drop_base64 = bool(getattr(settings, "CHECKPOINTER_DROP_BASE64", True))
    return max_messages, max_chars, drop_base64
