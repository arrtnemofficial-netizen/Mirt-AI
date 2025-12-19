from __future__ import annotations

from src.services.trim_policy import (
    get_checkpoint_compaction,
    get_llm_history_limit,
    get_state_message_limit,
)


def test_trim_policy_returns_ints() -> None:
    llm_limit = get_llm_history_limit()
    state_limit = get_state_message_limit()
    max_messages, max_chars, drop_base64 = get_checkpoint_compaction()

    assert isinstance(llm_limit, int)
    assert isinstance(state_limit, int)
    assert isinstance(max_messages, int)
    assert isinstance(max_chars, int)
    assert isinstance(drop_base64, bool)
