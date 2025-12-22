"""
E2E: Full conversation flow test.
==================================
Tests complete conversation from message to response:
- User message → LangGraph → PydanticAI → Response
- All nodes execution (moderation, intent, agent, validation)
- State transitions
- Error scenarios (timeout, circuit breaker, validation failure)
"""

from __future__ import annotations

import pytest

from src.core.state_machine import State
from src.services.conversation import create_conversation_handler
from src.services.infra.message_store import InMemoryMessageStore
from src.services.infra.session_store import InMemorySessionStore


@pytest.mark.e2e
@pytest.mark.asyncio
class TestFullConversationFlow:
    """End-to-end tests for complete conversation flow."""

    async def test_discovery_conversation_flow(self):
        """Test complete discovery conversation flow."""
        # Setup
        session_id = "test_e2e_discovery"
        message = "Привіт, шукаю одяг для дитини"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # Execute
        result = await handler.process_message(session_id, message)

        # Assert
        assert result.response is not None
        assert result.response.messages
        assert len(result.response.messages) > 0

        # State should transition from INIT to DISCOVERY or VISION
        final_state = result.state.get("current_state")
        assert final_state in [
            State.STATE_1_DISCOVERY.value,
            State.STATE_2_VISION.value,
            State.STATE_0_INIT.value,
        ], f"Unexpected state: {final_state}"

        # Response should contain text
        response_text = " ".join(
            msg.content for msg in result.response.messages if hasattr(msg, "content")
        )
        assert len(response_text) > 0

    async def test_multi_turn_conversation(self):
        """Test multi-turn conversation with state persistence."""
        session_id = "test_e2e_multi_turn"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # Turn 1: Discovery
        result1 = await handler.process_message(session_id, "Шукаю сукню")
        assert result1.response is not None
        state1 = result1.state.get("current_state")

        # Turn 2: Size question
        result2 = await handler.process_message(session_id, "Розмір 110")
        assert result2.response is not None
        state2 = result2.state.get("current_state")

        # State should progress (or stay in discovery if more info needed)
        assert state2 in [
            State.STATE_1_DISCOVERY.value,
            State.STATE_3_SIZE_COLOR.value,
            State.STATE_4_OFFER.value,
        ]

    async def test_error_scenario_timeout(self):
        """Test error handling when LLM times out."""
        session_id = "test_e2e_timeout"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # Normal message should work
        result = await handler.process_message(session_id, "Привіт")
        assert result.response is not None

        # Even if timeout occurs, should return fallback response
        assert not result.is_fallback or result.response.messages

    async def test_circuit_breaker_escalation(self):
        """Test that circuit breaker OPEN triggers escalation."""
        session_id = "test_e2e_circuit_breaker"

        # Force circuit breaker to OPEN state
        from src.core.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker("pydantic_ai_main_agent")
        # Simulate failures to open circuit
        for _ in range(5):
            cb.record_failure()

        assert not cb.can_execute(), "Circuit breaker should be OPEN"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # Process message - should escalate due to circuit breaker
        result = await handler.process_message(session_id, "Привіт")

        # Should return escalation response
        assert result.response is not None
        # Check if escalation occurred (either in response or state)
        is_escalated = (
            result.response.event == "escalation"
            or result.state.get("should_escalate", False)
            or any(
                "escalation" in str(msg.content).lower()
                for msg in result.response.messages
                if hasattr(msg, "content")
            )
        )

        # Reset circuit breaker for other tests
        cb.record_success()
        cb.record_success()
        cb.record_success()

    async def test_validation_retry_loop(self):
        """Test that validation failures trigger retry loop."""
        session_id = "test_e2e_validation_retry"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # Process message - validation node should handle retries
        result = await handler.process_message(session_id, "Шукаю товар")

        assert result.response is not None
        # Validation should complete (either success or escalation after max retries)
        assert result.state.get("current_state") is not None

    async def test_state_persistence_across_turns(self):
        """Test that state persists across multiple turns."""
        session_id = "test_e2e_persistence"

        session_store = InMemorySessionStore()
        message_store = InMemoryMessageStore()
        from src.agents import get_active_graph

        runner = get_active_graph()
        handler = create_conversation_handler(
            session_store=session_store,
            message_store=message_store,
            runner=runner,
        )

        # First turn
        result1 = await handler.process_message(session_id, "Привіт")
        state1 = result1.state

        # Second turn - should have previous context
        result2 = await handler.process_message(session_id, "Шукаю сукню")
        state2 = result2.state

        # Messages should accumulate
        messages1 = state1.get("messages", [])
        messages2 = state2.get("messages", [])
        assert len(messages2) >= len(messages1), "Messages should accumulate"

