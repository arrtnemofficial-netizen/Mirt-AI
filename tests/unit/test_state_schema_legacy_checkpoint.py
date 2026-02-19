import pytest

from src.core.state_schema import RETRY_BUFFER, StateSchema
from src.core.state_machine import State, get_default_dialog_phase_for_state


def test_legacy_checkpoint_unknown_keys_are_preserved_in_legacy_extra():
    payload = {
        "session_id": "legacy-1",
        "current_state": "STATE_4_OFFER",
        "dialog_phase": "OFFER_MADE",
        "deprecated_field": {"a": 1},
        "saved_checkpoint_id": "cp-123",
    }

    state = StateSchema(**payload)

    assert "deprecated_field" not in state.model_dump()
    assert state.legacy_extra["deprecated_field"] == {"a": 1}
    assert state["saved_checkpoint_id"] == "cp-123"

    serialized = state.model_dump()
    restored = StateSchema.model_validate(serialized)
    assert restored.legacy_extra["saved_checkpoint_id"] == "cp-123"


def test_legacy_checkpoint_invalid_phase_is_normalized_by_state():
    state = StateSchema(
        session_id="legacy-2",
        current_state=State.STATE_3_SIZE_COLOR.value,
        dialog_phase="INIT",
    )

    expected_phase = get_default_dialog_phase_for_state(State.STATE_3_SIZE_COLOR)
    assert state.dialog_phase == expected_phase


def test_retry_count_buffer_invariant():
    state_ok = StateSchema(
        session_id="legacy-3",
        retry_count=4,
        max_retries=3,
    )
    assert state_ok.retry_count == state_ok.max_retries + RETRY_BUFFER

    with pytest.raises(ValueError):
        StateSchema(
            session_id="legacy-4",
            retry_count=5,
            max_retries=3,
        )


def test_agent_moderation_and_tool_plan_typed_serialization_roundtrip():
    payload = {
        "session_id": "legacy-5",
        "agent_response": {
            "event": "simple_answer",
            "messages": [{"type": "text", "content": "ok"}],
            "products": [],
            "metadata": {
                "session_id": "legacy-5",
                "current_state": "STATE_0_INIT",
                "intent": "UNKNOWN_OR_EMPTY",
                "escalation_level": "NONE",
            },
        },
        "moderation_result": {
            "status": "allow",
            "score": 0.1,
            "reason": "clean",
            "categories": ["safe"],
        },
        "tool_plan_result": {
            "status": "planned",
            "selected_tool": "crm_lookup",
            "confidence": 0.88,
            "steps": ["lookup", "enrich"],
        },
        "metadata": {
            "session_id": "legacy-5",
            "channel": "telegram",
        },
    }

    state = StateSchema.model_validate(payload)
    dumped = state.model_dump()

    assert dumped["metadata"]["channel"] == "telegram"
    assert dumped["moderation_result"]["status"] == "allow"
    assert dumped["tool_plan_result"]["selected_tool"] == "crm_lookup"

    restored = StateSchema.model_validate_json(state.model_dump_json())
    assert restored.session_id == "legacy-5"
    assert restored.tool_plan_result and restored.tool_plan_result["confidence"] == 0.88
