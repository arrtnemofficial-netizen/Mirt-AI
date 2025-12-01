import json

import pytest

from src.core.models import AgentResponse, Message, Metadata, Product
from src.integrations.manychat.webhook import (
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
    ManychatWebhook,
)
from src.services.session_store import InMemorySessionStore


class DummyRunner:
    def __init__(self, agent_response: AgentResponse):
        self.agent_response = agent_response

    async def ainvoke(self, state, config=None):
        # Build assistant message in OUTPUT_CONTRACT format like real nodes
        assistant_content = {
            "event": self.agent_response.event,
            "messages": [m.model_dump() for m in self.agent_response.messages],
            "products": [p.model_dump() for p in self.agent_response.products],
            "metadata": self.agent_response.metadata.model_dump(),
        }

        if self.agent_response.escalation:
            assistant_content["escalation"] = self.agent_response.escalation.model_dump()

        # Use json.dumps() for proper JSON format (conversation handler expects JSON)
        json_content = json.dumps(assistant_content)
        state["messages"].append({"role": "assistant", "content": json_content})
        state["current_state"] = self.agent_response.metadata.current_state
        # Set agent_response like real nodes do (line 157 in agent_node.py)
        state["agent_response"] = self.agent_response.model_dump()
        # Ensure escalation_level is preserved in state
        if hasattr(self.agent_response.metadata, 'escalation_level'):
            state["escalation_level"] = self.agent_response.metadata.escalation_level
        return state


@pytest.mark.asyncio
async def test_manychat_handle_returns_messages():
    """Test basic ManyChat response with messages."""
    response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Привіт"), Message(content="Як можу допомогти?")],
        products=[],
        metadata=Metadata(current_state="STATE_1_DISCOVERY", intent="GREETING_ONLY"),
    )
    runner = DummyRunner(response)
    store = InMemorySessionStore()
    handler = ManychatWebhook(store, runner=runner)

    payload = {"subscriber": {"id": "abc"}, "message": {"text": "hi"}}

    output = await handler.handle(payload)

    # Check v2 format structure
    assert output["version"] == "v2"
    assert "content" in output
    assert "messages" in output["content"]

    # Check messages
    messages = output["content"]["messages"]
    assert messages[0]["text"].startswith("Привіт")
    assert messages[1]["text"].startswith("Як можу")

    # Check debug metadata
    assert output["_debug"]["current_state"] == "STATE_1_DISCOVERY"
    assert output["_debug"]["intent"] == "GREETING_ONLY"


@pytest.mark.asyncio
async def test_manychat_custom_fields():
    """Test Custom Field values in response."""
    response = AgentResponse(
        event="simple_answer",
        messages=[Message(content="Ось сукня")],
        products=[
            Product.from_legacy({
                "product_id": 123,
                "name": "Сукня Анна",
                "price": 1200,
                "size": "122-128",
                "color": "синій",
                "photo_url": "https://example.com/photo.jpg",
            })
        ],
        metadata=Metadata(current_state="STATE_4_OFFER", intent="DISCOVERY_OR_QUESTION"),
    )
    runner = DummyRunner(response)
    store = InMemorySessionStore()
    handler = ManychatWebhook(store, runner=runner)

    payload = {"subscriber": {"id": "abc"}, "message": {"text": "покажи сукню"}}
    output = await handler.handle(payload)

    # Check set_field_values
    field_values = output["set_field_values"]
    field_dict = {f["field_name"]: f["field_value"] for f in field_values}

    assert field_dict[FIELD_AI_STATE] == "STATE_4_OFFER"
    assert field_dict[FIELD_AI_INTENT] == "DISCOVERY_OR_QUESTION"
    assert field_dict[FIELD_LAST_PRODUCT] == "Сукня Анна"


@pytest.mark.asyncio
async def test_manychat_tags():
    """Test tags in response."""
    response = AgentResponse(
        event="escalation",
        messages=[Message(content="Передаю менеджеру")],
        products=[],
        metadata=Metadata(
            current_state="STATE_8_COMPLAINT", intent="COMPLAINT", escalation_level="L2"
        ),
    )
    runner = DummyRunner(response)
    store = InMemorySessionStore()
    handler = ManychatWebhook(store, runner=runner)

    payload = {"subscriber": {"id": "abc"}, "message": {"text": "у мене проблема"}}
    output = await handler.handle(payload)

    # Check tags
    assert TAG_AI_RESPONDED in output["add_tag"]
    assert TAG_NEEDS_HUMAN in output["add_tag"]


@pytest.mark.asyncio
async def test_manychat_quick_replies():
    """Test Quick Reply buttons based on state."""
    response = AgentResponse(
        event="clarifying_question",
        messages=[Message(content="Що шукаєте?")],
        products=[],
        metadata=Metadata(current_state="STATE_1_DISCOVERY", intent="GREETING_ONLY"),
    )
    runner = DummyRunner(response)
    store = InMemorySessionStore()
    handler = ManychatWebhook(store, runner=runner)

    payload = {"subscriber": {"id": "abc"}, "message": {"text": "привіт"}}
    output = await handler.handle(payload)

    # Check quick replies for discovery state
    quick_replies = output["content"]["quick_replies"]
    captions = [r["caption"] for r in quick_replies]

    assert "👗 Сукні" in captions
    assert "👔 Костюми" in captions
    assert "🧥 Тренчі" in captions
