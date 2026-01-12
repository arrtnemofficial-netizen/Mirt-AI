"""
Agent Node - Main LLM processing (Refactored).
==============================================
Orchestrator node that coordinates pre-processing, LLM execution, and post-processing.
Decomposed into:
- helpers/agent_pre.py: Snippets, Policy, Colors, Deps
- helpers/agent_post.py: SSOT, Cart, Fallbacks, Phase Transition
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from src.core.state_machine import State
from src.core.debug_logger import debug_log
from src.services.observability import log_agent_step, log_trace, track_metric

# Helpers
from src.agents.langgraph.nodes.helpers.agent_pre import (
    check_policy_snippets,
    handle_color_gallery,
    prepare_llm_dependencies,
)
from src.agents.langgraph.nodes.helpers.agent_post import (
    apply_ssot_state_transition,
    update_cart_and_products,
    fallback_parsing_logic,
    determine_final_dialog_phase,
)
from src.agents.langgraph.nodes.helpers.policy_snippets import _reset_policy_counters

# PydanticAI
from src.agents.pydantic.support_agent import run_support
from src.agents.pydantic.models import (
    SupportResponse,
    PaymentResponse,
    MessageItem,
    ResponseMetadata,
)

logger = logging.getLogger(__name__)


async def agent_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    Main Agent Node (Orchestrator).

    Flow:
    1. Extract user message
    2. Check Policy/Snippets (Pre-LLM)
    3. Check Color Gallery Requests (Pre-LLM)
    4. Prepare LLM Dependencies (Deps, Prompts, History)
    5. Execute LLM (Support or Payment Agent)
    6. Apply SSOT Overrides (State/Intent)
    7. Update Cart (Add/Merge products)
    8. Apply Fallback Parsing (Size/Color extraction)
    9. Determine Final Dialog Phase
    10. Construct & Return Response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    current_state = state.get("current_state", State.STATE_0_INIT.value)
    
    # 1. Extract User Message
    from src.agents.langgraph.nodes.utils import extract_user_message
    user_message = extract_user_message(state.get("messages", [])) or ""
    
    if not user_message:
        return {"step_number": state.get("step_number", 0) + 1}

    # 2. Check Policy/Snippets
    snippet_result = check_policy_snippets(state, user_message, session_id)
    if snippet_result:
        return snippet_result

    # 3. Check Color Gallery
    color_result = handle_color_gallery(state, user_message, current_state)
    if color_result:
        return color_result

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="agent",
            phase=state.get("dialog_phase", "?"),
            state_name=current_state,
            extra={"intent": state.get("detected_intent"), "msg": user_message},
        )

    try:
        # 4. Prepare LLM Dependencies
        # Note: We need SSOT transition data for payment sub-phase injection
        from src.agents.langgraph.fsm.transition_reducer import compute_transition
        transition_data = compute_transition(
            state=state,
            intent=state.get("detected_intent") or "DISCOVERY_OR_QUESTION",
            has_image=state.get("has_image", False),
            user_message=user_message,
        )

        deps, state_for_llm = prepare_llm_dependencies(state, current_state, transition_data)

        # 5. Execute LLM
        llm_start_time = time.perf_counter()
        
        if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
            # Payment Agent
            from src.agents.pydantic.payment_agent import run_payment
            
            payment_response: PaymentResponse = await run_payment(
                message=user_message,
                deps=deps,
                message_history=None,
            )
            
            # Convert to SupportResponse structure
            messages = [MessageItem(type="text", content=payment_response.reply_to_user)]
            
            # Handle extracted customer data
            metadata_dict = deps.metadata.model_dump() if hasattr(deps, 'metadata') else {}
            customer_data_dict = {}
            if payment_response.customer_data:
                if payment_response.customer_data.name: customer_data_dict["customer_name"] = payment_response.customer_data.name
                if payment_response.customer_data.phone: customer_data_dict["customer_phone"] = payment_response.customer_data.phone
                if payment_response.customer_data.city: customer_data_dict["customer_city"] = payment_response.customer_data.city
                if payment_response.customer_data.nova_poshta: customer_data_dict["customer_nova_poshta"] = payment_response.customer_data.nova_poshta
            
            response_metadata = ResponseMetadata(
                session_id=metadata_dict.get("session_id", session_id),
                current_state=State.STATE_5_PAYMENT_DELIVERY.value,
                intent="PAYMENT_DELIVERY",
                escalation_level="NONE",
            )
            
            response = SupportResponse(
                event="clarifying_question" if payment_response.missing_fields else "simple_answer",
                messages=messages,
                products=[],
                metadata=response_metadata,
            )
            # Attach customer data for post-processing
            response.customer_data = payment_response.customer_data

        else:
            # Support Agent
            response: SupportResponse = await run_support(
                message=user_message,
                deps=deps,
                message_history=None,
            )
            customer_data_dict = {}

        llm_latency_ms = (time.perf_counter() - llm_start_time) * 1000.0
        track_metric("llm_latency_ms", llm_latency_ms, {"state": current_state, "intent": response.metadata.intent or "unknown"})

        # 6. Runtime Guard: "Blind" Photo Ident check
        # If agent claims PHOTO_IDENT but no vision processing occurred, suppress it
        has_image = state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
        vision_processed = bool(
            state.get("metadata", {}).get("vision_confidence") is not None
            or state.get("metadata", {}).get("vision_greeted", False)
            or current_state == State.STATE_2_VISION.value
        )
        if has_image and response.metadata.intent == "PHOTO_IDENT" and not vision_processed:
            logger.warning("[SESSION %s] Suppressing PHOTO_IDENT (no vision context)", session_id)
            track_metric("agent_photo_ident_suppressed", 1, {"session_id": session_id})
            response.metadata.intent = "DISCOVERY_OR_QUESTION"

        # 7. Apply SSOT Overrides (State/Intent)
        final_state, final_intent = apply_ssot_state_transition(
            state, response.metadata.current_state, response.metadata.intent, user_message
        )
        
        # 8. Update Cart & Products
        final_products = update_cart_and_products(
            state, response.products, user_message, current_state
        )
        
        # 9. Fallback Parsing
        final_products = fallback_parsing_logic(
            state, final_products, user_message, response.messages
        )

        # Metadata Updates
        metadata_update = state.get("metadata", {}).copy()
        metadata_update.update(customer_data_dict)
        metadata_update["current_state"] = final_state
        metadata_update["intent"] = final_intent

        if final_products:
            first_name = str(final_products[0].get("name") or "").strip()
            if first_name:
                metadata_update["current_product_name"] = first_name

        # Handle Greeting Flag
        vision_greeted_before = bool(metadata_update.get("vision_greeted", False))
        greeting_in_response = any("менеджер соф" in str(m.content).lower() for m in response.messages)
        if not vision_greeted_before and greeting_in_response:
             metadata_update["vision_greeted"] = True

        # Special Case: Recalculate Payment Sub-Phase if customer data changed
        if customer_data_dict and final_state == State.STATE_5_PAYMENT_DELIVERY.value:
            from src.agents.langgraph.state_prompts import get_payment_sub_phase
            temp_state = {**state, "metadata": metadata_update}
            new_sub_phase = get_payment_sub_phase(temp_state)
            metadata_update["_computed_payment_sub_phase"] = new_sub_phase

        # 10. Determine Final Dialog Phase
        old_dialog_phase = state.get("dialog_phase", "INIT")
        final_dialog_phase = determine_final_dialog_phase(
            final_state, response.event, final_intent, final_products, response.metadata, {**state, "metadata": metadata_update}
        )

        if old_dialog_phase != final_dialog_phase:
            metadata_update = _reset_policy_counters(metadata_update)

        # Build Response
        assistant_content = {
            "event": response.event,
            "messages": [m.model_dump() for m in response.messages],
            "products": final_products,  # These are already dicts
            "metadata": {
                **response.metadata.model_dump(),
                "current_state": final_state,
                "intent": final_intent,
            },
        }
        if response.escalation:
            assistant_content["escalation"] = response.escalation.model_dump()
        if response.reasoning:
            assistant_content["reasoning"] = response.reasoning

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Async Trace Logging
        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="agent_node",
            status="SUCCESS",
            state_name=final_state,
            prompt_key=f"state.{final_state}",
            input_snapshot={"message": user_message},
            output_snapshot=assistant_content,
            latency_ms=latency_ms,
        )

        # Missing Product Info Exit
        if response.escalation and response.escalation.reason == "missing_product_info":
             return {
                "current_state": final_state,
                "detected_intent": final_intent,
                "dialog_phase": "ESCALATED",
                "messages": [{"role": "assistant", "content": "Передаю ваш запит менеджеру..."}],
                "metadata": {**metadata_update, "exit_condition": "missing_product_info"},
                "should_escalate": True,
                "escalation_reason": "Missing info",
                "step_number": state.get("step_number", 0) + 1,
             }

        return {
            "current_state": final_state,
            "detected_intent": final_intent,
            "dialog_phase": final_dialog_phase,
            "messages": [{"role": "assistant", "content": str(assistant_content)}],
            "metadata": metadata_update,
            "selected_products": final_products,
            "should_escalate": response.event == "escalation",
            "escalation_reason": response.escalation.reason if response.escalation else None,
            "step_number": state.get("step_number", 0) + 1,
            "agent_response": response.model_dump(),
        }

    except Exception as e:
        logger.error("Agent node failed for session %s: %s", session_id, e, exc_info=True)
        await log_trace(session_id, trace_id, "agent_node", "ERROR", str(e), "SYSTEM", current_state)
        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Agent error: {e}"],
            "step_number": state.get("step_number", 0) + 1,
        }
