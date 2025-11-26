import pytest

from src.core.models import AgentResponse, Message, Metadata
from src.integrations.manychat.webhook import ManychatWebhook
from src.services.session_store import InMemorySessionStore


class DummyRunner:
    def __init__(self, agent_response: AgentResponse):
        self.agent_response = agent_response

    async def ainvoke(self, state):
        state["messages"].append({"role": "assistant", "content": self.agent_response.model_dump_json()})
        state["metadata"] = self.agent_response.metadata.model_dump()
        state["current_state"] = self.agent_response.metadata.current_state
        return state


@pytest.mark.asyncio
async def test_manychat_handle_returns_messages():
    response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Привіт"), Message(content="Як можу допомогти?")],
        products=[],
        metadata=Metadata(current_state="STATE1_DISCOVERY"),
    )
    runner = DummyRunner(response)
    store = InMemorySessionStore()
    handler = ManychatWebhook(store, runner=runner)

    payload = {"subscriber": {"id": "abc"}, "message": {"text": "hi"}}

    output = await handler.handle(payload)

    assert output["metadata"]["current_state"] == "STATE1_DISCOVERY"
    assert output["messages"][0]["text"].startswith("Привіт")
    assert output["messages"][1]["text"].startswith("Як можу")
