"""
Unit tests for Policy Snippets helper functions.
"""

import pytest

from src.agents.langgraph.nodes.helpers.policy_snippets import (
    _get_no_count,
    _get_offtopic_count,
    _increment_no_count,
    _increment_offtopic_count,
    _is_clarification_context,
    _is_color_request_context,
    _reset_policy_counters,
    detect_explicit_new_product,
    detect_user_says_no,
)


def test_detect_explicit_new_product_expanded_patterns():
    """Test that expanded patterns are detected."""
    state = {}
    
    # Original patterns
    assert detect_explicit_new_product("новий товар", state) is True
    assert detect_explicit_new_product("інший товар", state) is True
    
    # New expanded patterns
    assert detect_explicit_new_product("це ще одне", state) is True
    assert detect_explicit_new_product("покажи ще", state) is True
    assert detect_explicit_new_product("інша модель", state) is True
    assert detect_explicit_new_product("хочу подивитись інше", state) is True
    assert detect_explicit_new_product("нове фото", state) is True
    
    # Should not match
    assert detect_explicit_new_product("покажи сукні", state) is False
    assert detect_explicit_new_product("які кольори", state) is False


def test_detect_explicit_new_product_with_color_context():
    """Test that color requests are NOT treated as new product."""
    # State with product context (ongoing conversation)
    state = {
        "selected_products": [{"name": "Сукня Анна", "size": "122/128"}],
    }

    # State with metadata-only product context (SSOT)
    state_metadata = {
        "metadata": {"current_product_name": "Kapriz"},
    }
    
    # Color requests should NOT trigger new product
    assert detect_explicit_new_product("покажи інший колір", state) is False
    assert detect_explicit_new_product("які кольори є", state) is False
    assert detect_explicit_new_product("інші кольори", state) is False
    assert detect_explicit_new_product("покажи інший колір", state_metadata) is False
    
    # But explicit new product should still work
    assert detect_explicit_new_product("це новий товар", state) is True
    assert detect_explicit_new_product("інший товар", state) is True


def test_is_color_request_context():
    """Test color request context detection."""
    state = {
        "selected_products": [{"name": "Сукня Анна"}],
    }
    
    # Should detect color requests
    assert _is_color_request_context("покажи інший колір", state) is True
    assert _is_color_request_context("які кольори є", state) is True
    
    # Should NOT detect if no product context
    state_no_product = {}

    # Should detect if metadata has product context
    state_metadata = {"metadata": {"current_product_name": "Kapriz"}}
    assert _is_color_request_context("покажи інший колір", state_metadata) is True
    assert _is_color_request_context("покажи інший колір", state_no_product) is False
    
    # Should NOT detect if not about color
    assert _is_color_request_context("покажи сукні", state) is False


def test_offtopic_counter_increments():
    """Test that off-topic counter increments correctly."""
    metadata = {}
    
    assert _get_offtopic_count(metadata) == 0
    
    metadata = _increment_offtopic_count(metadata)
    assert _get_offtopic_count(metadata) == 1
    
    metadata = _increment_offtopic_count(metadata)
    assert _get_offtopic_count(metadata) == 2


def test_no_counter_increments():
    """Test that 'no' counter increments correctly."""
    metadata = {}
    
    assert _get_no_count(metadata) == 0
    
    metadata = _increment_no_count(metadata)
    assert _get_no_count(metadata) == 1
    
    metadata = _increment_no_count(metadata)
    assert _get_no_count(metadata) == 2


def test_reset_policy_counters():
    """Test that policy counters are reset correctly."""
    metadata = {
        "policy_stats": {
            "offtopic_count": 5,
            "no_count": 3,
        }
    }
    
    metadata = _reset_policy_counters(metadata)
    
    assert _get_offtopic_count(metadata) == 0
    assert _get_no_count(metadata) == 0


def test_no_detection_clarification_vs_refusal():
    """Test that clarification is distinguished from refusal."""
    state = {}
    
    # Clarifications (should NOT be treated as refusal)
    is_refusal, reason = detect_user_says_no("ні, не підходить розмір", state)
    assert is_refusal is False
    assert reason == "clarification"
    
    is_refusal, reason = detect_user_says_no("ні, не той колір", state)
    assert is_refusal is False
    assert reason == "clarification"
    
    is_refusal, reason = detect_user_says_no("ні, інший розмір", state)
    assert is_refusal is False
    assert reason == "clarification"
    
    # Actual refusals (should be treated as refusal)
    is_refusal, reason = detect_user_says_no("ні", state)
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("не хочу", state)
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("передумала", state)
    assert is_refusal is True
    assert reason == "refusal"
    
    is_refusal, reason = detect_user_says_no("відміняємо", state)
    assert is_refusal is True
    assert reason == "refusal"


def test_is_clarification_context():
    """Test clarification context detection."""
    # Should detect clarifications
    assert _is_clarification_context("ні, не підходить розмір") is True
    assert _is_clarification_context("ні, не той колір") is True
    assert _is_clarification_context("ні, інший розмір") is True
    
    # Should NOT detect standalone "no"
    assert _is_clarification_context("ні") is False
    assert _is_clarification_context("не хочу") is False


@pytest.mark.asyncio
async def test_offtopic_counter_escalation():
    """Test that escalation occurs after 2+ off-topic questions."""
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy
    
    state = {
        "session_id": "test_offtopic_escalation",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "metadata": {
            "policy_stats": {
                "offtopic_count": 2,  # Already 2, next should escalate
            }
        },
        "detected_intent": "PRODUCT_CATEGORY",
        "messages": [{"role": "user", "content": "що ще є"}],  # Use text that won't trigger "no" detection
    }
    
    result = maybe_apply_snippet_policy(
        state,
        detected_intent="PRODUCT_CATEGORY",
        user_text="що ще є",
    )
    
    assert result is not None
    assert result.get("should_escalate") is True
    assert "Too many off-topic questions" in result.get("escalation_reason", "")


@pytest.mark.asyncio
async def test_no_counter_escalation():
    """Test that escalation occurs after 3+ 'no' responses."""
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy
    
    state = {
        "session_id": "test_no_escalation",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "metadata": {
            "policy_stats": {
            "no_count": 2,  # Already 2, next should escalate
            }
        },
        "detected_intent": "PAYMENT_DELIVERY",
        "messages": [{"role": "user", "content": "ні"}],
    }
    
    result = maybe_apply_snippet_policy(
        state,
        detected_intent="PAYMENT_DELIVERY",
        user_text="ні",
    )
    
    assert result is not None
    assert result.get("should_escalate") is True
    assert "User refused 3+ times" in result.get("escalation_reason", "")
    assert result.get("agent_response", {}).get("metadata", {}).get("should_notify_manager") is True


@pytest.mark.asyncio
async def test_no_counter_increments_only_on_refusal():
    """Test that counter increments only on actual refusal, not clarification."""
    from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy
    
    state = {
        "session_id": "test_no_clarification",
        "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
        "current_state": "STATE_5_PAYMENT_DELIVERY",
        "metadata": {
            "policy_stats": {
                "no_count": 0,
            }
        },
        "detected_intent": "PAYMENT_DELIVERY",
        "messages": [{"role": "user", "content": "ні, не підходить розмір"}],
    }
    
    result = maybe_apply_snippet_policy(
        state,
        detected_intent="PAYMENT_DELIVERY",
        user_text="ні, не підходить розмір",
    )
    
    # Clarification should NOT trigger snippet policy (returns None)
    assert result is None
    
    # Counter should NOT increment
    assert _get_no_count(state["metadata"]) == 0

