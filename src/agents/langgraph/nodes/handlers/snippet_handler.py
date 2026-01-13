
"""
Snippet Handler.
================
Responsible for policy checks and snippet-only responses.
Handles:
1. Checking against policy snippets (e.g. "no" in payment).
2. Optimizing response by skipping LLM if snippet is sufficient.
"""

import logging
from typing import Any

from src.core.state_machine import State
from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy
from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.fsm.policy import determine_response_policy
from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header

logger = logging.getLogger(__name__)


def check_snippet_policy(
    state: dict[str, Any],
    user_message: str,
    detected_intent: str | None,
) -> dict[str, Any] | None:
    """
    Check if we should return a snippet-only response (bypass LLM).

    Args:
        state: Current state.
        user_message: User inputs.
        detected_intent: Pre-computed intent.

    Returns:
        State update dict if handled, None otherwise.
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # 1. Simple Policy Check
    snippet_response = maybe_apply_snippet_policy(
        state,
        detected_intent=detected_intent,
        user_text=user_message,
    )

    if snippet_response:
        return {
            **snippet_response,
            "step_number": state.get("step_number", 0) + 1,
        }

    # 2. SSOT Response Policy Check (Optimization)
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    transition = compute_transition(
        state=state,
        intent=detected_intent or "DISCOVERY_OR_QUESTION",
        has_image=has_image,
        user_message=user_message,
    )

    response_policy = determine_response_policy(
        next_state=transition.next_state,
        payment_sub_phase=transition.payment_sub_phase,
        metadata=state.get("metadata", {}),
        session_id=session_id,
    )

    # If policy says "use snippet" AND "no LLM required"
    if response_policy.snippet_name and not response_policy.use_llm:
        snippets = get_snippet_by_header(response_policy.snippet_name)
        if snippets:
            snippet_text = "\n\n".join(snippets)

            # Update metadata (Idempotency)
            metadata_update = state.get("metadata", {}).copy()
            if response_policy.snippet_sent_flag:
                metadata_update[response_policy.snippet_sent_flag] = True

            logger.info(
                "[SESSION %s] 🎯 Snippet-only response (no LLM): snippet=%s, flag=%s",
                session_id,
                response_policy.snippet_name,
                response_policy.snippet_sent_flag,
            )

            return {
                "current_state": transition.next_state,
                "dialog_phase": transition.dialog_phase,
                "metadata": metadata_update,
                "agent_response": {
                    "event": "simple_answer",
                    "messages": [{"type": "text", "content": snippet_text}],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": transition.next_state,
                        "intent": "PAYMENT_DELIVERY" if transition.next_state == State.STATE_5_PAYMENT_DELIVERY.value else detected_intent,
                    },
                },
                "step_number": state.get("step_number", 0) + 1,
            }
        else:
            logger.warning(
                "[SESSION %s] ⚠️ Snippet '%s' not found, falling back to LLM",
                session_id,
                response_policy.snippet_name,
            )

    return None
