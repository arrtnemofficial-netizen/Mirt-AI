"""
Unit tests for StateSchema/ConversationState dict-like .get() behavior.
======================================================================
Ensures state.get("missing", default) returns default and state.get("tool_errors", []) works.
"""

import pytest
from src.agents.langgraph.state import create_initial_state
from src.core.state_schema import StateSchema


def test_state_get_missing_returns_default():
    """state.get('missing_key', default) must return default, not raise."""
    state = create_initial_state(session_id="test")
    assert state.get("nonexistent_field", "default") == "default"
    assert state.get("another_missing", 42) == 42


def test_state_get_tool_errors_returns_list():
    """state.get('tool_errors', []) must return list (empty or populated)."""
    state = create_initial_state(session_id="test")
    result = state.get("tool_errors", [])
    assert isinstance(result, list)
    assert result == []


def test_state_get_tool_errors_populated():
    """When tool_errors has values, .get must return them."""
    state = create_initial_state(session_id="test", tool_errors=["error1"])
    result = state.get("tool_errors", [])
    assert result == ["error1"]


def test_state_get_raises_keyerror_for_missing_without_default():
    """state['missing'] must raise KeyError (not AttributeError) so .get() works."""
    state = create_initial_state(session_id="test")
    with pytest.raises(KeyError):
        _ = state["nonexistent_key"]


def test_state_schema_has_tool_errors_field():
    """StateSchema must declare tool_errors for legacy checkpoint compatibility."""
    assert "tool_errors" in StateSchema.model_fields
