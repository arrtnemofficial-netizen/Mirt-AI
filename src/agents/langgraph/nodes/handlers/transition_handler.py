
"""
Transition Handler.
===================
Responsible for computing the next state using SSOT Reducer.
Handles:
1. Transition computation (Reducer).
2. Global Priority Overrides (Complaint, Vision).
3. Payment State Preservation (Context).
"""

import logging
from typing import Any

from src.core.state_machine import State
from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.pydantic.models import SupportResponse

logger = logging.getLogger(__name__)


def finalize_transition(
    state: dict[str, Any],
    response: SupportResponse,
    user_message: str,
) -> tuple[str, str, dict[str, Any]]:
    """
    Compute final state and intent using SSOT.

    Args:
        state: Current state dict.
        response: Response from Dispatch Handler.
        user_message: User inputs.

    Returns:
        tuple[new_state, final_intent, transition_metadata]
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    current_state = state.get("current_state", State.STATE_0_INIT.value)
    
    # 1. Extract context
    llm_intent = response.metadata.intent
    intent = llm_intent
    payment_context = state.get("payment_info_buffer") or {}
    preserve_payment_state = payment_context.get("preserve_state", False)
    transition_source = "llm"

    # STATE_5 strict precedence: intent node (or deterministic re-check) first, LLM second.
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        detected_intent = state.get("detected_intent")
        if not detected_intent or detected_intent == "UNKNOWN_OR_EMPTY":
            # If master router skipped intent node, compute deterministic intent from text.
            from src.agents.langgraph.nodes.intent import detect_intent_from_text

            has_image = state.get("has_image", False) or state.get("metadata", {}).get(
                "has_image", False
            )
            detected_intent = detect_intent_from_text(
                user_message or "",
                has_image=has_image,
                current_state=current_state,
            ).primary_intent

        if detected_intent and detected_intent != "UNKNOWN_OR_EMPTY":
            intent = str(detected_intent)
            transition_source = "intent_node"
        elif llm_intent:
            intent = llm_intent
            transition_source = "llm"
        else:
            intent = "PAYMENT_DELIVERY"
            transition_source = "override"
    
    # 2. Check Global Priorities (immutable)
    global_priority_intents = {"COMPLAINT", "PHOTO_IDENT"}
    if intent in global_priority_intents:
        logger.debug(
            "[SESSION %s] Global priority intent %s - skipping SSOT override",
            session_id,
            intent,
        )
        return response.metadata.current_state, intent, {
            "transition_reason": f"global_priority_intent:{intent}",
            "transition_source": transition_source,
            "payment_sub_phase": None,
            "dialog_phase": state.get("dialog_phase"),
            "has_deferred_intents": bool(state.get("metadata", {}).get("deferred_intents", [])),
        }

    # 3. Compute SSOT Transition
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    deferred_intents = state.get("metadata", {}).get("deferred_intents", [])
    transition = compute_transition(
        state=state,
        intent=intent or "DISCOVERY_OR_QUESTION",
        has_image=has_image,
        user_message=user_message,
        deferred_intents=deferred_intents,
    )

    # 4. Apply Overrides
    if preserve_payment_state and current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        # Override: Force stay in Payment
        logger.info(
            "[SESSION %s] 🛡️ Payment state preserved: STATE_5_PAYMENT_DELIVERY (preserve_state=True)",
            session_id,
        )
        return State.STATE_5_PAYMENT_DELIVERY.value, intent, {
            "transition_reason": "payment_preserve_state_override",
            "transition_source": "override",
            "payment_sub_phase": transition.payment_sub_phase,
            "dialog_phase": transition.dialog_phase,
            "has_deferred_intents": transition.has_deferred_intents,
        }
    
    # 5. Apply SSOT Decision
    # If SSOT says X, but LLM says Y -> Trust SSOT (Transition Reducer)
    new_state = transition.next_state
    
    if new_state != response.metadata.current_state:
        logger.info(
            "[SESSION %s] SSOT Override: LLM state=%s, SSOT state=%s.",
            session_id,
            response.metadata.current_state,
            new_state,
        )
        # Fix intent if we forced into Payment
        if new_state == State.STATE_5_PAYMENT_DELIVERY.value and intent != "PAYMENT_DELIVERY":
            intent = "PAYMENT_DELIVERY"

    return new_state, intent, {
        "transition_reason": transition.reason,
        "transition_source": transition_source,
        "payment_sub_phase": transition.payment_sub_phase,
        "dialog_phase": transition.dialog_phase,
        "has_deferred_intents": transition.has_deferred_intents,
    }
