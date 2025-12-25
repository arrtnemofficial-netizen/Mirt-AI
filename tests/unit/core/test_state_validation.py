"""Unit tests for state structure validation."""

from typing import Any

import pytest

from src.core.conversation_state import (
    ConversationState,
    create_initial_state,
    validate_state_structure,
)


class TestValidateStateStructure:
    """Tests for validate_state_structure() function."""

    def test_valid_state(self):
        """Valid state should pass validation."""
        state = create_initial_state(session_id="test_123")
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is True
        assert len(errors) == 0

    def test_none_state(self):
        """None state should fail validation."""
        is_valid, errors = validate_state_structure(None)
        
        assert is_valid is False
        assert len(errors) == 1
        assert "State is None" in errors[0]

    def test_non_dict_state(self):
        """Non-dict state should fail validation."""
        is_valid, errors = validate_state_structure("not a dict")
        
        assert is_valid is False
        assert len(errors) == 1
        assert "State must be a dict" in errors[0]

    def test_missing_session_id(self):
        """State without session_id should fail."""
        state: ConversationState = {
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("session_id" in err for err in errors)

    def test_missing_messages(self):
        """State without messages should fail."""
        state: ConversationState = {
            "session_id": "test_123",
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("messages" in err for err in errors)

    def test_missing_metadata(self):
        """State without metadata should fail."""
        state: ConversationState = {
            "session_id": "test_123",
            "messages": [],
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("metadata" in err for err in errors)

    def test_missing_current_state(self):
        """State without current_state should fail."""
        state: ConversationState = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("current_state" in err for err in errors)

    def test_wrong_type_messages(self):
        """State with messages as non-list should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": "not a list",  # type: ignore
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("messages" in err and "list" in err for err in errors)

    def test_wrong_type_metadata(self):
        """State with metadata as non-dict should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": "not a dict",  # type: ignore
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("metadata" in err and "dict" in err for err in errors)

    def test_wrong_type_session_id(self):
        """State with session_id as non-string should fail."""
        state: dict[str, Any] = {
            "session_id": 12345,  # type: ignore
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("session_id" in err and "str" in err for err in errors)

    def test_wrong_type_current_state(self):
        """State with current_state as non-string should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": 12345,  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("current_state" in err and "str" in err for err in errors)

    def test_none_session_id(self):
        """State with None session_id should fail."""
        state: dict[str, Any] = {
            "session_id": None,  # type: ignore
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("session_id" in err and "None" in err for err in errors)

    def test_none_current_state(self):
        """State with None current_state should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": None,  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("current_state" in err and "None" in err for err in errors)

    def test_invalid_message_structure(self):
        """State with invalid message structure should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": ["not a dict", 12345],  # type: ignore
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("Message at index" in err for err in errors)

    def test_valid_messages(self):
        """State with valid message structure should pass."""
        state: ConversationState = {
            "session_id": "test_123",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
            "metadata": {},
            "current_state": "STATE_0_INIT",
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is True
        assert len(errors) == 0

    def test_wrong_type_selected_products(self):
        """State with selected_products as non-list should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
            "selected_products": "not a list",  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("selected_products" in err and "list" in err for err in errors)

    def test_wrong_type_should_escalate(self):
        """State with should_escalate as non-bool should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
            "should_escalate": "not a bool",  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("should_escalate" in err and "bool" in err for err in errors)

    def test_wrong_type_retry_count(self):
        """State with retry_count as non-int should fail."""
        state: dict[str, Any] = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
            "retry_count": "not an int",  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert any("retry_count" in err and "int" in err for err in errors)

    def test_none_optional_fields_allowed(self):
        """None values for optional fields should be allowed."""
        state: ConversationState = {
            "session_id": "test_123",
            "messages": [],
            "metadata": {},
            "current_state": "STATE_0_INIT",
            "selected_products": None,  # type: ignore
            "detected_intent": None,
            "image_url": None,
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is True
        assert len(errors) == 0

    def test_production_like_state(self):
        """Production-like state with all fields should pass."""
        state = create_initial_state(
            session_id="prod_session_123",
            messages=[
                {"role": "user", "content": "Привіт"},
                {"role": "assistant", "content": "Вітаю!"},
            ],
            metadata={
                "channel": "telegram",
                "language": "uk",
                "vision_greeted": True,
            },
        )
        state["selected_products"] = [
            {"id": 1, "name": "Лагуна", "price": 1500.0}
        ]
        state["retry_count"] = 0
        state["step_number"] = 5
        
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is True
        assert len(errors) == 0

    def test_corrupted_state_from_db(self):
        """Simulate corrupted state from database."""
        # This simulates what might happen if DB returns corrupted data
        state: dict[str, Any] = {
            "session_id": "corrupted_123",
            "messages": "corrupted",  # type: ignore
            "metadata": None,  # type: ignore
            "current_state": 999,  # type: ignore
            "selected_products": "not a list",  # type: ignore
        }
        is_valid, errors = validate_state_structure(state)
        
        assert is_valid is False
        assert len(errors) > 0
        # Should catch multiple errors
        assert len(errors) >= 3

