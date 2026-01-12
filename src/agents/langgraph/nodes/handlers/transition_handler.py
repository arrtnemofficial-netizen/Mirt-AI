
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
) -> tuple[str, str]:
    """
    Compute final state and intent using SSOT.

    Args:
        state: Current state dict.
        response: Response from Dispatch Handler.
        user_message: User inputs.

    Returns:
        tuple[new_state, final_intent]
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    current_state = state.get("current_state", State.STATE_0_INIT.value)
    
    # 1. Extract context
    intent = response.metadata.intent
    payment_context = state.get("_payment_context", {})
    preserve_payment_state = payment_context.get("preserve_state", False)
    
    # 2. Check Global Priorities (immutable)
    global_priority_intents = {"COMPLAINT", "PHOTO_IDENT"}
    if intent in global_priority_intents:
        logger.debug(
            "[SESSION %s] Global priority intent %s - skipping SSOT override",
            session_id,
            intent,
        )
        return response.metadata.current_state, intent

    # 3. Compute SSOT Transition
    has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
    transition = compute_transition(
        state=state,
        intent=intent or "DISCOVERY_OR_QUESTION",
        has_image=has_image,
        user_message=user_message,
    )

    # 4. Apply Overrides
    if preserve_payment_state and current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        # Override: Force stay in Payment
        logger.info(
            "[SESSION %s] 🛡️ Payment state preserved: STATE_5_PAYMENT_DELIVERY (preserve_state=True)",
            session_id,
        )
        return State.STATE_5_PAYMENT_DELIVERY.value, intent
    
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
    
    return new_state, intent
