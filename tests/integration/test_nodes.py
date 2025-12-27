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


@pytest.mark.asyncio
async def test_intent_node_photo_during_payment_routes_as_payment_not_photo_ident():
    """
    Regression: photo during payment proof phase must NOT force PHOTO_IDENT.

    In production logs, has_image=True in WAITING_FOR_PAYMENT_PROOF used to override
    escalation and route to vision, restarting dialog with greeting.
    """
    from src.agents.langgraph.nodes.intent import intent_detection_node
    from src.core.state_machine import State

    state = create_minimal_state("test_photo_mid_payment")
    state["current_state"] = State.STATE_5_PAYMENT_DELIVERY.value
    state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
    state["has_image"] = True
    state["image_url"] = "https://example.com/proof.jpg"
    state["metadata"] = {
        "session_id": "test_photo_mid_payment",
        "has_image": True,
        "image_url": "https://example.com/proof.jpg",
        "vision_greeted": True,
    }
    state["messages"] = [{"role": "user", "content": "Ось квитанція"}]

    output = await intent_detection_node(state)
    errors = validate_node_output(output, "intent_detection_node")
    assert not errors, f"Validation errors: {errors}"

    assert output.get("has_image") is True
    assert output.get("detected_intent") == "PAYMENT_DELIVERY", (
        f"Mid-payment photo must return PAYMENT_DELIVERY, got {output.get('detected_intent')}"
    )


@pytest.mark.asyncio
async def test_intent_node_explicit_new_product_trigger():
    """
    Test that explicit "new product" trigger routes to PHOTO_IDENT regardless of phase.
    """
    from src.agents.langgraph.nodes.intent import intent_detection_node
    from src.core.state_machine import State

    # Test in mid-conversation phase (should normally route to agent)
    state = create_minimal_state("test_explicit_new_product")
    state["current_state"] = State.STATE_3_SIZE_COLOR.value
    state["dialog_phase"] = "WAITING_FOR_SIZE"
    state["has_image"] = True
    state["image_url"] = "https://example.com/new_product.jpg"
    state["metadata"] = {
        "session_id": "test_explicit_new_product",
        "has_image": True,
        "image_url": "https://example.com/new_product.jpg",
        "vision_greeted": True,  # Already greeted, so normally would NOT route to vision
    }
    state["messages"] = [{"role": "user", "content": "це новий товар"}]

    output = await intent_detection_node(state)
    errors = validate_node_output(output, "intent_detection_node")
    assert not errors, f"Validation errors: {errors}"

    # Explicit trigger should override phase-aware routing
    assert output.get("has_image") is True
    assert output.get("detected_intent") == "PHOTO_IDENT", (
        f"Explicit 'new product' trigger must return PHOTO_IDENT, got {output.get('detected_intent')}"
    )
    assert output.get("metadata", {}).get("explicit_new_product_trigger") is True


@pytest.mark.asyncio
async def test_intent_node_offtopic_in_payment_allowed():
    """
    Test that off-topic intents (PRODUCT_CATEGORY, REQUEST_PHOTO) are allowed in payment state.
    """
    from src.agents.langgraph.nodes.intent import intent_detection_node
    from src.core.state_machine import State

    # Test PRODUCT_CATEGORY in payment state
    state = create_minimal_state("test_offtopic_payment")
    state["current_state"] = State.STATE_5_PAYMENT_DELIVERY.value
    state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
    state["messages"] = [{"role": "user", "content": "покажи сукні"}]

    output = await intent_detection_node(state)
    errors = validate_node_output(output, "intent_detection_node")
    assert not errors, f"Validation errors: {errors}"

    # Off-topic intent should be allowed (not forced to PAYMENT_DELIVERY)
    assert output.get("detected_intent") == "PRODUCT_CATEGORY", (
        f"Off-topic in payment should return PRODUCT_CATEGORY, got {output.get('detected_intent')}"
    )


@pytest.mark.asyncio
async def test_policy_snippets_user_says_no():
    """
    Test that policy_snippets detects "user says no" and returns snippet response.
    """
    from src.agents.langgraph.nodes.helpers.policy_snippets import (
        detect_user_says_no,
        maybe_apply_snippet_policy,
    )

    # Test detection (now returns tuple)
    is_refusal, reason = detect_user_says_no("ні")
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("не хочу")
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("передумала")
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("відміняємо")
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("так")
    assert is_refusal is False
    
    is_refusal, reason = detect_user_says_no("хочу купити")
    assert is_refusal is False
    
    # Test clarification (should NOT be treated as refusal)
    is_refusal, reason = detect_user_says_no("ні, не підходить розмір")
    assert is_refusal is False
    assert reason == "clarification"

    # Test snippet policy in payment phase
    state = create_minimal_state("test_no_in_payment")
    state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
    state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
    state["messages"] = [{"role": "user", "content": "ні"}]
    state["detected_intent"] = "PAYMENT_DELIVERY"
    state["metadata"] = {"policy_stats": {"no_count": 0}}

    result = maybe_apply_snippet_policy(state, detected_intent="PAYMENT_DELIVERY", user_text="ні")
    
    assert result is not None, "Snippet policy should return response for 'no' in payment phase"
    assert "messages" in result
    assert "agent_response" in result
    assert result.get("dialog_phase") == "WAITING_FOR_PAYMENT_PROOF", "Should keep dialog_phase unchanged"
    assert result.get("agent_response", {}).get("metadata", {}).get("policy_case") == "user_says_no"
    assert result.get("agent_response", {}).get("metadata", {}).get("should_notify_manager") is True
    # Check that counter was incremented
    assert result.get("metadata", {}).get("policy_stats", {}).get("no_count") == 1


@pytest.mark.asyncio
async def test_policy_snippets_payment_problem():
    """
    Test that policy_snippets detects payment problems and flags for manager notification.
    """
    from src.agents.langgraph.nodes.helpers.policy_snippets import (
        detect_payment_problem,
        maybe_apply_snippet_policy,
    )

    # Test detection
    assert detect_payment_problem("не отримується оплата") is True
    assert detect_payment_problem("не проходить") is True
    assert detect_payment_problem("помилка оплати") is True
    assert detect_payment_problem("не можу оплатити") is True
    assert detect_payment_problem("все добре") is False

    # Test snippet policy in payment phase
    state = create_minimal_state("test_payment_problem")
    state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
    state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
    state["messages"] = [{"role": "user", "content": "не отримується оплата"}]
    state["detected_intent"] = "PAYMENT_DELIVERY"

    result = maybe_apply_snippet_policy(
        state, detected_intent="PAYMENT_DELIVERY", user_text="не отримується оплата"
    )
    
    assert result is not None, "Snippet policy should return response for payment problem"
    assert "agent_response" in result
    assert result.get("dialog_phase") == "WAITING_FOR_PAYMENT_PROOF", "Should keep dialog_phase unchanged"
    assert result.get("agent_response", {}).get("metadata", {}).get("policy_case") == "payment_problem"
    assert result.get("agent_response", {}).get("metadata", {}).get("should_notify_manager") is True


@pytest.mark.asyncio
async def test_policy_snippets_offtopic_in_payment():
    """
    Test that policy_snippets handles off-topic questions in payment phase.
    """
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy

    state = create_minimal_state("test_offtopic_payment")
    state["current_state"] = "STATE_5_PAYMENT_DELIVERY"
    state["dialog_phase"] = "WAITING_FOR_PAYMENT_PROOF"
    state["messages"] = [{"role": "user", "content": "що ще є"}]
    state["detected_intent"] = "PRODUCT_CATEGORY"
    state["metadata"] = {"policy_stats": {"offtopic_count": 0}}

    result = maybe_apply_snippet_policy(
        state, detected_intent="PRODUCT_CATEGORY", user_text="що ще є"
    )
    
    assert result is not None, "Snippet policy should return response for off-topic in payment"
    assert "messages" in result
    assert result.get("dialog_phase") == "WAITING_FOR_PAYMENT_PROOF", "Should keep dialog_phase unchanged"
    assert result.get("agent_response", {}).get("metadata", {}).get("policy_case") == "offtopic_in_payment"
    # Check that counter was incremented
    assert result.get("metadata", {}).get("policy_stats", {}).get("offtopic_count") == 1


@pytest.mark.asyncio
async def test_policy_counters_reset_on_phase_change():
    """
    Test that policy counters are reset when dialog phase changes.
    """
    from src.agents.langgraph.nodes.helpers.policy_snippets import _reset_policy_counters, _get_offtopic_count, _get_no_count

    metadata = {
        "policy_stats": {
            "offtopic_count": 2,
            "no_count": 1,
        }
    }
    
    # Reset counters
    updated_metadata = _reset_policy_counters(metadata.copy())
    
    assert _get_offtopic_count(updated_metadata) == 0
    assert _get_no_count(updated_metadata) == 0


@pytest.mark.asyncio
async def test_payment_reminder_by_phase():
    """
    Test that payment reminder is generated correctly for each phase.
    """
    from src.agents.langgraph.nodes.helpers.policy_snippets import _get_payment_reminder_by_phase

    reminder_proof = _get_payment_reminder_by_phase("WAITING_FOR_PAYMENT_PROOF")
    assert reminder_proof is not None
    assert "квитанцію" in reminder_proof.lower()
    
    reminder_method = _get_payment_reminder_by_phase("WAITING_FOR_PAYMENT_METHOD")
    assert reminder_method is not None
    assert "спосіб оплати" in reminder_method.lower() or "оплата" in reminder_method.lower()
    
    reminder_delivery = _get_payment_reminder_by_phase("WAITING_FOR_DELIVERY_DATA")
    assert reminder_delivery is not None
    assert "дані" in reminder_delivery.lower() or "доставк" in reminder_delivery.lower()
    
    # Non-payment phase should return None
    assert _get_payment_reminder_by_phase("INIT") is None


# =============================================================================
# VISION NODE TESTS (Integration - requires API)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("openai", reason="OpenAI not installed"), reason="Requires OpenAI API"
)
async def test_vision_node_deps_have_image_url():
    """Test that vision node correctly passes image_url to deps."""
    from unittest.mock import patch

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
    assert captured_deps.image_url == "https://example.com/test_image.jpg", (
        f"image_url not passed correctly: {captured_deps.image_url}"
    )

    errors = validate_node_output(output, "vision_node")
    assert not errors, f"Validation errors: {errors}"


# =============================================================================
# AGENT NODE TESTS (Integration - requires API)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("openai", reason="OpenAI not installed"), reason="Requires OpenAI API"
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
        from src.agents.pydantic.models import (
            MessageItem,
            ProductMatch,
            ResponseMetadata,
            SupportResponse,
        )

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Ок")],
            products=[
                ProductMatch(
                    id=2,
                    name="Товар 2",
                    price=900,
                    size="122",
                    color="білий",
                    photo_url="https://x/y.jpg",
                )
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
        from src.agents.pydantic.models import (
            MessageItem,
            ProductMatch,
            ResponseMetadata,
            SupportResponse,
        )

        return SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Додала")],
            products=[
                ProductMatch(
                    id=1,
                    name="Товар 1",
                    price=1000,
                    size="122",
                    color="чорний",
                    photo_url="https://x/1.jpg",
                ),
                ProductMatch(
                    id=3,
                    name="Товар 3",
                    price=500,
                    size="128",
                    color="сірий",
                    photo_url="https://x/3.jpg",
                ),
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
