
"""
Agent Node - Main LLM processing.
=================================
Refactored V6 Engine: Slim Orchestrator using Functional Handlers.
Responsibility:
- Orchestration of decoupled handlers.
- Dependency Injection.
- Logging & Observability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.agents.langgraph.nodes.handlers.cart_handler import merge_cart
from src.agents.langgraph.nodes.handlers.color_handler import handle_color_request
from src.agents.langgraph.nodes.handlers.dispatch_handler import execute_agent_dispatch

# Handlers (Ironclad Logic)
from src.agents.langgraph.nodes.handlers.snippet_handler import check_snippet_policy
from src.agents.langgraph.nodes.handlers.transition_handler import finalize_transition
from src.agents.langgraph.nodes.helpers.intent_instructions import get_instructions_for_intent
from src.agents.langgraph.nodes.helpers.size_parsing import (
    extract_size_from_response,
    height_to_size,
)
from src.agents.langgraph.routers.base import to_schema
from src.agents.langgraph.state_prompts import resolve_state_prompt

# PydanticAI Deps
from src.agents.pydantic.deps import create_deps_from_state

# Core & Config
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.services.conversation import trim_message_history

# Services
from src.services.observability import track_metric


# Legacy aliases for backward compatibility import
_height_to_size = height_to_size
_extract_size_from_response = extract_size_from_response
_get_instructions_for_intent = get_instructions_for_intent

logger = logging.getLogger(__name__)


async def agent_node(
    state: dict[str, Any],
    runner: Any | None = None,
) -> dict[str, Any]:
    """
    General agent node orchestrator.
    Delegates actual logic to specialized handlers.
    """
    schema_state = to_schema(state)
    session_id = schema_state.session_id or schema_state.metadata.get("session_id", "")
    current_state_str = schema_state.current_state

    # 1. Extract User Message
    from .utils import extract_user_message
    user_message = extract_user_message(schema_state.messages)

    if not user_message:
        return {"step_number": schema_state.step_number + 1}

    user_text = user_message if isinstance(user_message, str) else str(user_message)
    detected_intent = schema_state.detected_intent

    # =========================================================================
    # HANDLER 1: SNIPPET POLICY (Optimization Gate)
    # =========================================================================
    snippet_result = check_snippet_policy(schema_state.to_dict(), user_text, detected_intent)
    if snippet_result:
        return snippet_result

    # =========================================================================
    # HANDLER 2: COLORS (Visualizer)
    # =========================================================================
    color_result = handle_color_request(schema_state.to_dict(), user_text)
    if color_result:
        return color_result

    # =========================================================================
    # PREPARE FOR LLM (Orchestration)
    # =========================================================================

    # Debug logging
    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="agent",
            phase=schema_state.dialog_phase,
            state_name=current_state_str,
            extra={"intent": detected_intent, "msg": user_text},
        )

    # Context Trimming
    trimmed_messages = trim_message_history(schema_state.messages)
    state_for_llm = {**schema_state.to_dict(), "messages": trimmed_messages}

    # Dependency Injection
    deps = create_deps_from_state(state_for_llm)

    # Inject State Prompt
    # Uses resolve_state_prompt which handles all dynamic sub-phase logic
    state_prompt = resolve_state_prompt(schema_state.to_dict())
    if state_prompt:
        deps.state_specific_prompt = state_prompt

    # =========================================================================
    # HANDLER 3: DISPATCH (The Brain)
    # =========================================================================
    try:
        llm_start_time = time.perf_counter()

        response = await execute_agent_dispatch(
            user_message=user_text,
            deps=deps,
            current_state=current_state_str,
            message_history=None, # PydanticAI handles history via deps/system prompt usually
        )

        llm_latency_ms = (time.perf_counter() - llm_start_time) * 1000.0
        track_metric("llm_latency_ms", llm_latency_ms, {"state": current_state_str})

        logger.info(
            "Agent response for session %s: event=%s, state=%s, intent=%s, products=%d",
            session_id,
            response.event,
            response.metadata.current_state,
            response.metadata.intent,
            len(response.products),
        )

        # =====================================================================
        # POST-PROCESSING & STATE UPDATE
        # =====================================================================

        # Special Case: Vision Greeting Deduplication
        # (Can move to helper if needed, but acceptable here as distinct logic)
        vision_greeted_before = bool(schema_state.metadata.get("vision_greeted", False))
        if (
            current_state_str == State.STATE_3_SIZE_COLOR.value
            and vision_greeted_before
            and len(response.messages) > 1
        ):
            first_content = response.messages[0].content.strip().lower()
            if first_content.startswith("вітаю") or "mirt_ua" in first_content:
                response.messages = response.messages[1:]

        # =====================================================================
        # HANDLER 4: TRANSITION (SSOT)
        # =====================================================================
        # Updates response.metadata.current_state and intent based on SSOT reducer
        new_state_str, final_intent = finalize_transition(schema_state.to_dict(), response, user_text)

        # Apply updates to response object for consistency
        response.metadata.current_state = new_state_str
        response.metadata.intent = final_intent

        # =====================================================================
        # HANDLER 5: CART (Merger)
        # =====================================================================
        # Strict Mode enabled for Payment State
        is_payment_state = current_state_str == State.STATE_5_PAYMENT_DELIVERY.value

        updated_products = merge_cart(
            current_products=schema_state.selected_products,
            new_products=[p.model_dump() for p in response.products],
            user_text=user_text,
            strict_mode=is_payment_state
        )

        # =====================================================================
        # FINAL PAYLOAD CONSTRUCTION
        # =====================================================================

        # Convert response to dict for persistence
        # SupportResponse -> dict
        agent_response_payload = response.model_dump()

        # Prepare metadata update
        metadata_update = dict(schema_state.metadata)

        # Import customer data from response if present (from Dispatch Handler)
        if response.customer_data:
            c_data = response.customer_data
            if c_data.name:
                metadata_update["customer_name"] = c_data.name
            if c_data.phone:
                metadata_update["customer_phone"] = c_data.phone
            if c_data.city:
                metadata_update["customer_city"] = c_data.city
            if c_data.nova_poshta:
                metadata_update["customer_nova_poshta"] = c_data.nova_poshta

        metadata_update["current_state"] = new_state_str
        metadata_update["intent"] = final_intent

        return {
            "current_state": new_state_str,
            "detected_intent": final_intent,
            "dialog_phase": schema_state.dialog_phase, # Let reducer handle phase in future
            # CRITICAL FIX: Convert internal MessageItem (type='text'/'image')
            # to LangChain compatible dict (type='ai', content=...)
            "messages": [
                {
                    "type": "ai",
                    "content": m.content,
                    "additional_kwargs": {"original_type": m.type} # Preserve original type in kwargs
                }
                for m in response.messages
            ],
            "metadata": metadata_update,
            "selected_products": updated_products,
            "should_escalate": response.event == "escalation",
            "escalation_reason": response.escalation.reason if response.escalation else None,
            "step_number": schema_state.step_number + 1,
            "last_error": None,
            "agent_response": agent_response_payload,
        }

    except Exception as e:
        logger.error("Agent execution failed: %s", e, exc_info=True)
        # Fail safe return
        return {
            "current_state": current_state_str,
            "error": str(e),
            "step_number": schema_state.step_number + 1,
        }
