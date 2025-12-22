"""Tests for ConversationHandler runner validation.

Tests cover:
- Handler creation with None runner (should fail)
- Handler creation with invalid runner (should fail)
- Handler creation with valid runner (should succeed)
- Agent invocation with None runner (should fail gracefully)
"""

import pytest

from src.services.conversation.exceptions import AgentInvocationError
from src.services.conversation.handler import ConversationHandler, create_conversation_handler
from src.services.infra.message_store import MessageStore


class MockSessionStore:
    """Mock session store for testing."""
    
    def get(self, session_id: str):
        return None
    
    def save(self, session_id: str, state: dict) -> None:
        pass


class MockMessageStore(MessageStore):
    """Mock message store for testing."""
    
    def append(self, message) -> None:
        pass


class ValidRunner:
    """Mock runner that implements GraphRunner protocol."""
    
    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        """Mock ainvoke that returns the state."""
        return state


class InvalidRunner:
    """Mock runner that doesn't implement ainvoke."""
    
    def invoke(self, state: dict) -> dict:
        """Wrong method name."""
        return state


def test_create_handler_with_none_runner():
    """Test that creating handler with None runner raises ValueError."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    
    with pytest.raises(ValueError, match="runner cannot be None"):
        create_conversation_handler(
            session_store=store,
            message_store=msg_store,
            runner=None,  # type: ignore
        )


def test_create_handler_with_invalid_runner():
    """Test that creating handler with invalid runner raises ValueError."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    invalid_runner = InvalidRunner()
    
    with pytest.raises(ValueError, match="must implement GraphRunner protocol"):
        create_conversation_handler(
            session_store=store,
            message_store=msg_store,
            runner=invalid_runner,  # type: ignore
        )


def test_create_handler_with_valid_runner():
    """Test that creating handler with valid runner succeeds."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    valid_runner = ValidRunner()
    
    handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=valid_runner,  # type: ignore
    )
    
    assert handler is not None
    assert handler.runner is valid_runner


@pytest.mark.asyncio
async def test_invoke_agent_with_none_runner():
    """Test that invoking agent with None runner raises AgentInvocationError."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    valid_runner = ValidRunner()
    
    handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=valid_runner,  # type: ignore
    )
    
    # Manually set runner to None to simulate the bug
    handler.runner = None  # type: ignore
    
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "metadata": {"session_id": "test-session"},
        "current_state": "STATE_0_INIT",
    }
    
    with pytest.raises(AgentInvocationError, match="Runner is None"):
        await handler._invoke_agent(state)


@pytest.mark.asyncio
async def test_invoke_agent_with_invalid_runner():
    """Test that invoking agent with invalid runner raises AgentInvocationError."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    valid_runner = ValidRunner()
    
    handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=valid_runner,  # type: ignore
    )
    
    # Manually set runner to invalid object
    handler.runner = InvalidRunner()  # type: ignore
    
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "metadata": {"session_id": "test-session"},
        "current_state": "STATE_0_INIT",
    }
    
    with pytest.raises(AgentInvocationError, match="does not have ainvoke method"):
        await handler._invoke_agent(state)


@pytest.mark.asyncio
async def test_invoke_agent_with_valid_runner():
    """Test that invoking agent with valid runner succeeds."""
    store = MockSessionStore()
    msg_store = MockMessageStore()
    valid_runner = ValidRunner()
    
    handler = create_conversation_handler(
        session_store=store,
        message_store=msg_store,
        runner=valid_runner,  # type: ignore
    )
    
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "metadata": {"session_id": "test-session"},
        "current_state": "STATE_0_INIT",
    }
    
    result = await handler._invoke_agent(state)
    assert result == state  # ValidRunner just returns the state

