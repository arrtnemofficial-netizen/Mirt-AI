"""
Node Unit Tests - Validate each node returns valid ConversationState.
======================================================================
These tests ensure that each LangGraph node:
1. Accepts valid ConversationState
2. Returns valid ConversationState
3. Contains all required fields
4. Doesn't add "garbage" keys
"""

from typing import TYPE_CHECKING, Any

import pytest

from src.agents.langgraph.state import ConversationState


if TYPE_CHECKING:
    from src.agents.pydantic.deps import AgentDeps


# =============================================================================
# FIXTURES
# =============================================================================


def create_minimal_state(session_id: str = "test_session") -> dict[str, Any]:
    """Create minimal valid state for testing."""
    return {
        "messages": [{"role": "user", "content": "Привіт!"}],
        "session_id": session_id,
        "thread_id": session_id,
        "metadata": {"session_id": session_id},
        "current_state": "STATE_0_INIT",
        "step_number": 0,
    }


def create_vision_state(session_id: str = "test_vision") -> dict[str, Any]:
    """Create state with image for vision testing."""
    state = create_minimal_state(session_id)
    state["messages"] = [{"role": "user", "content": "Що це за товар?"}]
    state["image_url"] = "https://example.com/test_image.jpg"
    state["has_image"] = True
    state["metadata"]["has_image"] = True
    state["metadata"]["image_url"] = "https://example.com/test_image.jpg"
    return state


def create_offer_state(session_id: str = "test_offer") -> dict[str, Any]:
    """Create state with products for offer testing."""
    state = create_minimal_state(session_id)
    state["messages"] = [{"role": "user", "content": "Хочу цю сукню"}]
    state["current_state"] = "STATE_1_DISCOVERY"
    state["selected_products"] = [
        {"id": 1, "name": "Сукня Еліт", "price": 1300, "size": "116", "color": "рожева"}
    ]
    return state


def create_payment_state(session_id: str = "test_payment") -> dict[str, Any]:
    """Create state for payment testing."""
    state = create_offer_state(session_id)
    state["messages"] = [{"role": "user", "content": "Оформлюємо"}]
    state["current_state"] = "STATE_4_OFFER"
    state["offered_products"] = state["selected_products"]
    return state


# =============================================================================
# STATE VALIDATION HELPERS
# =============================================================================


REQUIRED_UPDATE_KEYS = {"step_number"}  # Minimum keys a node should return

ALLOWED_STATE_KEYS = set(ConversationState.__annotations__.keys())


def validate_node_output(output: dict[str, Any], node_name: str) -> list[str]:
    """Validate node output and return list of errors."""
    errors = []

    if not isinstance(output, dict):
        errors.append(f"{node_name}: Output is not a dict, got {type(output)}")
        return errors

    # Check for unknown keys (potential garbage)
    unknown_keys = set(output.keys()) - ALLOWED_STATE_KEYS
    if unknown_keys:
        errors.append(f"{node_name}: Unknown keys in output: {unknown_keys}")

    # Check step_number is updated
    if "step_number" not in output:
        errors.append(f"{node_name}: Missing 'step_number' in output")

    # Check messages format if present
    if "messages" in output:
        messages = output["messages"]
        if not isinstance(messages, list):
            errors.append(f"{node_name}: 'messages' is not a list")
        else:
            for i, msg in enumerate(messages):
                if not isinstance(msg, dict):
                    errors.append(f"{node_name}: messages[{i}] is not a dict")
                elif "role" not in msg or "content" not in msg:
                    errors.append(f"{node_name}: messages[{i}] missing role or content")

    return errors


# =============================================================================
# MODERATION NODE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_moderation_node_valid_input():
    """Test moderation node with valid input."""
    from src.agents.langgraph.nodes.moderation import moderation_node

    state = create_minimal_state()
    output = await moderation_node(state)

    errors = validate_node_output(output, "moderation_node")
    assert not errors, f"Validation errors: {errors}"

    # Moderation should always return moderation_result
    assert "moderation_result" in output
    assert "allowed" in output["moderation_result"]


@pytest.mark.asyncio
async def test_moderation_node_empty_message():
    """Test moderation node with empty message."""
    from src.agents.langgraph.nodes.moderation import moderation_node

    state = create_minimal_state()
    state["messages"] = []

    output = await moderation_node(state)
    errors = validate_node_output(output, "moderation_node")

    assert not errors, f"Validation errors: {errors}"
    # Should still return valid result
    assert output["moderation_result"]["allowed"] is True


# =============================================================================
# INTENT NODE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_intent_node_valid_input():
    """Test intent detection node with valid input."""
    from src.agents.langgraph.nodes.intent import intent_detection_node

    state = create_minimal_state()
    output = await intent_detection_node(state)

    errors = validate_node_output(output, "intent_detection_node")
    assert not errors, f"Validation errors: {errors}"

    # Intent should return detected_intent
    assert "detected_intent" in output
    assert output["detected_intent"] is not None


@pytest.mark.asyncio
async def test_intent_node_with_photo():
    """Test intent detection recognizes photo."""
    from src.agents.langgraph.nodes.intent import intent_detection_node

    state = create_vision_state()
    output = await intent_detection_node(state)

    errors = validate_node_output(output, "intent_detection_node")
    assert not errors, f"Validation errors: {errors}"

    # Should detect photo intent
    assert output.get("has_image") is True


# =============================================================================
# VISION NODE TESTS (Integration - requires API)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("openai", reason="OpenAI not installed"),
    reason="Requires OpenAI API"
)
async def test_vision_node_deps_have_image_url():
    """Test that vision node correctly passes image_url to deps."""
    from unittest.mock import AsyncMock, patch

    state = create_vision_state()

    # Mock run_vision to capture deps
    captured_deps: AgentDeps | None = None

    async def mock_run_vision(message, deps):
        nonlocal captured_deps
        captured_deps = deps
        # Return minimal valid response
        from src.agents.pydantic.models import VisionResponse
        return VisionResponse(
            reply_to_user="Тест",
            confidence=0.5,
            needs_clarification=False,
        )

    # Patch at the module level BEFORE importing vision_node
    with patch("src.agents.pydantic.vision_agent.run_vision", new=mock_run_vision):
        # Import inside patch context to ensure mock is used
        import importlib
        import src.agents.langgraph.nodes.vision as vision_module
        importlib.reload(vision_module)
        output = await vision_module.vision_node(state)

    # CRITICAL CHECK: Did image_url reach deps?
    assert captured_deps is not None, "run_vision was not called"
    assert captured_deps.has_image is True, "has_image not set in deps"
    assert captured_deps.image_url == "https://example.com/test_image.jpg", \
        f"image_url not passed correctly: {captured_deps.image_url}"

    errors = validate_node_output(output, "vision_node")
    assert not errors, f"Validation errors: {errors}"


# =============================================================================
# AGENT NODE TESTS (Integration - requires API)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("openai", reason="OpenAI not installed"),
    reason="Requires OpenAI API"
)
async def test_agent_node_returns_valid_state():
    """Test agent node returns valid ConversationState."""
    from unittest.mock import patch

    from src.agents.langgraph.nodes.agent import agent_node

    state = create_minimal_state()

    # Mock run_support
    async def mock_run_support(message, deps, message_history):
        from src.agents.pydantic.models import (
            MessageItem,
            ResponseMetadata,
            SupportResponse,
        )
        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Привіт! Чим можу допомогти?")],
            metadata=ResponseMetadata(
                session_id=deps.session_id,
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

    with patch("src.agents.langgraph.nodes.agent.run_support", mock_run_support):
        output = await agent_node(state)

    errors = validate_node_output(output, "agent_node")
    assert not errors, f"Validation errors: {errors}"

    # Agent should return agent_response
    assert "agent_response" in output
    assert output["agent_response"]["event"] == "simple_answer"


# =============================================================================
# OFFER NODE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_offer_node_with_products():
    """Test offer node with selected products."""
    from unittest.mock import patch

    from src.agents.langgraph.nodes.offer import offer_node

    state = create_offer_state()

    # Mock run_support
    async def mock_run_support(message, deps, message_history):
        from src.agents.pydantic.models import MessageItem, ResponseMetadata, SupportResponse
        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Чудовий вибір! Сукня Еліт - 1300 грн")],
            metadata=ResponseMetadata(
                session_id=deps.session_id,
                current_state="STATE_4_OFFER",
                intent="SIZE_HELP",
                escalation_level="NONE",
            ),
        )

    with patch("src.agents.langgraph.nodes.offer.run_support", mock_run_support):
        output = await offer_node(state)

    errors = validate_node_output(output, "offer_node")
    assert not errors, f"Validation errors: {errors}"

    # Should track offered products
    assert "offered_products" in output
    assert len(output["offered_products"]) == 1


@pytest.mark.asyncio
async def test_agent_node_appends_products_to_cart_on_add_keywords():
    from unittest.mock import patch

    from src.agents.langgraph.nodes.agent import agent_node
    from src.core.state_machine import State

    state = create_minimal_state("test_cart_merge")
    state["messages"] = [{"role": "user", "content": "Додай ще"}]
    state["current_state"] = State.STATE_1_DISCOVERY.value
    state["dialog_phase"] = "DISCOVERY"
    state["selected_products"] = [
        {"id": 1, "name": "Товар 1", "price": 1000, "size": "122", "color": "чорний"}
    ]

    async def mock_run_support(message, deps, message_history):
        from src.agents.pydantic.models import MessageItem, ProductMatch, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Ок")],
            products=[
                ProductMatch(id=2, name="Товар 2", price=900, size="122", color="білий", photo_url="https://x/y.jpg")
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id,
                current_state=State.STATE_1_DISCOVERY.value,
                intent="DISCOVERY_OR_QUESTION",
                escalation_level="NONE",
            ),
        )

    with patch("src.agents.langgraph.nodes.agent.run_support", mock_run_support):
        output = await agent_node(state)

    assert "selected_products" in output
    assert len(output["selected_products"]) == 2
    ids = {p.get("id") for p in output["selected_products"]}
    assert ids == {1, 2}


@pytest.mark.asyncio
async def test_upsell_node_merges_products_into_cart_dedup():
    from unittest.mock import patch

    from src.agents.langgraph.nodes.upsell import upsell_node
    from src.core.state_machine import State

    state = create_minimal_state("test_upsell_merge")
    state["messages"] = [{"role": "user", "content": "Так, додавай"}]
    state["current_state"] = State.STATE_6_UPSELL.value
    state["dialog_phase"] = "UPSELL_OFFERED"
    state["selected_products"] = [
        {"id": 1, "name": "Товар 1", "price": 1000, "size": "122", "color": "чорний"}
    ]
    state["offered_products"] = state["selected_products"]

    async def mock_run_support(message, deps, message_history):
        from src.agents.pydantic.models import MessageItem, ProductMatch, ResponseMetadata, SupportResponse

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Додала")],
            products=[
                ProductMatch(id=1, name="Товар 1", price=1000, size="122", color="чорний", photo_url="https://x/1.jpg"),
                ProductMatch(id=3, name="Товар 3", price=500, size="128", color="сірий", photo_url="https://x/3.jpg"),
            ],
            metadata=ResponseMetadata(
                session_id=deps.session_id,
                current_state=State.STATE_6_UPSELL.value,
                intent="DISCOVERY_OR_QUESTION",
                escalation_level="NONE",
            ),
        )

    with patch("src.agents.langgraph.nodes.upsell.run_support", mock_run_support):
        output = await upsell_node(state)

    assert output.get("dialog_phase") == "COMPLETED"
    assert "selected_products" in output
    assert len(output["selected_products"]) == 2
    ids = {p.get("id") for p in output["selected_products"]}
    assert ids == {1, 3}


# =============================================================================
# FULL FLOW TEST
# =============================================================================


@pytest.mark.asyncio
async def test_moderation_to_intent_flow():
    """Test state flows correctly from moderation to intent."""
    from src.agents.langgraph.nodes.intent import intent_detection_node
    from src.agents.langgraph.nodes.moderation import moderation_node

    # Start with minimal state
    state = create_minimal_state()

    # Step 1: Moderation
    mod_output = await moderation_node(state)
    assert mod_output["moderation_result"]["allowed"] is True

    # Merge output into state (simulating LangGraph)
    state.update(mod_output)

    # Step 2: Intent
    intent_output = await intent_detection_node(state)
    assert "detected_intent" in intent_output

    # State should still have messages
    assert "messages" in state
    assert len(state["messages"]) > 0


# =============================================================================
# IMAGE URL PROPAGATION TEST
# =============================================================================


def test_image_url_in_state_metadata():
    """Verify image_url is accessible from both state root and metadata."""
    state = create_vision_state()

    # Both paths should work
    url_from_root = state.get("image_url")
    url_from_metadata = state.get("metadata", {}).get("image_url")

    assert url_from_root == "https://example.com/test_image.jpg"
    assert url_from_metadata == "https://example.com/test_image.jpg"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
