import pytest

from src.services.conversation import ConversationHandler
from src.services.message_store import InMemoryMessageStore
from src.services.session_store import InMemorySessionStore


class PassthroughRunner:
    async def ainvoke(self, state, config=None):
        return state


def _stagnant_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "messages": [],
        "metadata": {"session_id": session_id},
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
    }


@pytest.mark.asyncio
async def test_guardrails_soft_recovery_after_10_stagnant_turns():
    store = InMemorySessionStore()
    msg_store = InMemoryMessageStore()
    handler = ConversationHandler(
        session_store=store, message_store=msg_store, runner=PassthroughRunner()
    )

    session_id = "sess_guard_10"

    store.save(session_id, _stagnant_state(session_id))

    last_state = None
    for _ in range(10):
        result = await handler.process_message(session_id, "ок", extra_metadata=None)
        last_state = result.state
        store.save(session_id, last_state)

    assert last_state is not None
    assert last_state.get("last_error") == "loop_guard_soft_recovery"
    assert last_state.get("current_state") == "STATE_0_INIT"
    assert last_state.get("dialog_phase") == "INIT"


@pytest.mark.asyncio
async def test_guardrails_escalation_after_20_stagnant_turns():
    store = InMemorySessionStore()
    msg_store = InMemoryMessageStore()
    handler = ConversationHandler(
        session_store=store, message_store=msg_store, runner=PassthroughRunner()
    )

    session_id = "sess_guard_20"

    store.save(session_id, _stagnant_state(session_id))

    last_state = None
    for _ in range(20):
        result = await handler.process_message(session_id, "ок", extra_metadata=None)
        last_state = result.state

        # Keep it stagnant even after soft-recovery so we can reach escalation.
        if last_state.get("dialog_phase") == "INIT":
            last_state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
            last_state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"

        store.save(session_id, last_state)

    assert last_state is not None
    assert last_state.get("last_error") == "loop_guard_escalation"
    assert last_state.get("current_state") == "STATE_8_COMPLAINT"
    assert last_state.get("dialog_phase") == "COMPLAINT"
    assert last_state.get("should_escalate") is True
    assert isinstance(last_state.get("agent_response"), dict)
