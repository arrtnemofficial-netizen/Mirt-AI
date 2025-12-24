"""
Agent Node - Main Orchestrator.
==============================
Coordinates:
- User Input (Tools)
- Logic/State Machine (Logic)
- Data Access (Catalog)
- LLM Execution (PydanticAI)

Refactored from monolithic agent.py.
"""
from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

# PydanticAI imports
from src.agents.pydantic.deps import create_deps_from_state
from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.prompt_registry import load_yaml_from_registry
from src.core.registry_keys import SystemKeys
from src.core.state_machine import State
from src.services.core.observability import log_agent_step, log_trace, track_metric
from src.services.domain.catalog.product_matcher import extract_requested_color

# Module imports
from . import catalog, logic, tools
from src.agents.langgraph.nodes.utils import extract_user_message, extract_height_from_text
from src.agents.langgraph.state_prompts import get_state_prompt, get_payment_sub_phase
from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header

if TYPE_CHECKING:
    from collections.abc import Callable
    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)


async def agent_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """
    General agent node using PydanticAI.
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    current_state = state.get("current_state", State.STATE_0_INIT.value)

    # OpenTelemetry tracing
    from src.services.core.observability import get_tracer, is_tracing_enabled

    tracer = get_tracer() if is_tracing_enabled() else None
    span = None
    if tracer:
        span = tracer.start_span("langgraph.agent_node")
        span.set_attribute("session_id", session_id)
        span.set_attribute("current_state", current_state)
        span.set_attribute("trace_id", trace_id)

    user_message = extract_user_message(state.get("messages", []))

    if not user_message:
        return {
            "step_number": state.get("step_number", 0) + 1,
        }

    # =========================================================================
    # COLOR CHECK (Catalog Logic)
    # =========================================================================
    if current_state == State.STATE_3_SIZE_COLOR.value:
        try:
            available_colors = state.get("metadata", {}).get("available_colors")
            if isinstance(available_colors, list) and available_colors:
                requested = extract_requested_color(user_message)
                if requested:
                    is_available, options = catalog.check_color_availability(
                        requested, available_colors
                    )
                    
                    if options and not is_available:
                        # Color block logic
                        options_text = ", ".join(options[:8])
                        snippet = get_snippet_by_header("COLOR_UNAVAILABLE")
                        if snippet:
                            reply_text = snippet[0].format(options=options_text)
                        else:
                            reply_text = options_text

                        agent_response_payload = {
                            "event": "simple_answer",
                            "messages": [{"type": "text", "content": reply_text}],
                            "products": state.get("selected_products", []) or [],
                            "metadata": {
                                "session_id": session_id,
                                "current_state": current_state,
                                "intent": "COLOR_HELP",
                                "escalation_level": "NONE",
                            },
                        }
                        
                        metadata_update = state.get("metadata", {}).copy()
                        metadata_update.update({"current_state": current_state, "intent": "COLOR_HELP"})
                        
                        return {
                            "current_state": current_state,
                            "detected_intent": "COLOR_HELP",
                            "dialog_phase": "WAITING_FOR_COLOR",
                            "messages": [{"role": "assistant", "content": str(agent_response_payload)}],
                            "metadata": metadata_update,
                            "selected_products": state.get("selected_products", []) or [],
                            "should_escalate": False,
                            "escalation_reason": None,
                            "step_number": state.get("step_number", 0) + 1,
                            "agent_response": agent_response_payload,
                        }
                        
                    elif options and is_available:
                        # Valid color selected - update state
                        selected_products = state.get("selected_products", []) or []
                        if selected_products:
                            first = dict(selected_products[0])
                            if not first.get("color"):
                                first["color"] = requested
                            selected_products = [first, *selected_products[1:]]
                            state = {
                                **state,
                                "selected_products": selected_products,
                                "metadata": {
                                    **state.get("metadata", {}),
                                    "selected_color": requested,
                                },
                            }
        except Exception:
            pass

    # =========================================================================
    # AUTO COLOR GALLERY (Universal - works at ANY state)
    # =========================================================================
    # Detect if user wants to see all color options with photos
    try:
        from src.agents.langgraph.rules.color_request import (
            detect_color_show_request,
            get_product_name_for_color_show,
        )
        from src.agents.langgraph.nodes.helpers.vision.product_colors import (
            get_product_colors,
        )
        
        if detect_color_show_request(user_message):
            product_name = get_product_name_for_color_show(state)
            
            if product_name:
                # Get all colors for this product
                all_colors = get_product_colors(product_name)
                
                if all_colors and len(all_colors) > 0:
                    # Build response with text + all color photos
                    messages_list: list[dict[str, str]] = []
                    
                    # First bubble: simple text
                    messages_list.append({
                        "type": "text",
                        "content": "У нас є кілька кольорів:"
                    })
                    
                    # Add all color photos
                    # Format: {"type": "image", "content": "url"} to match Message model
                    # Note: ManyChat doesn't support captions, but we store URL only in content
                    for color_info in all_colors:
                        color_name = color_info.get("color", "")
                        photo_url = color_info.get("photo_url", "")
                        
                        if photo_url:
                            # Store only URL in content (Message model format)
                            # Caption can be added via newline separator for other platforms if needed
                            messages_list.append({
                                "type": "image",
                                "content": photo_url,  # URL only (ManyChat doesn't support captions)
                            })
                    
                    # Build agent response payload
                    agent_response_payload = {
                        "event": "simple_answer",
                        "messages": messages_list,
                        "products": state.get("selected_products", []) or [],
                        "metadata": {
                            "session_id": session_id,
                            "current_state": current_state,
                            "intent": "COLOR_GALLERY",
                            "escalation_level": "NONE",
                        },
                    }
                    
                    logger.info(
                        "[COLOR_GALLERY] Auto-sending %d color photos for product '%s'",
                        len(all_colors),
                        product_name
                    )
                    
                    metadata_update = state.get("metadata", {}).copy()
                    metadata_update.update({
                        "current_state": current_state,
                        "intent": "COLOR_GALLERY",
                    })
                    
                    return {
                        "current_state": current_state,
                        "detected_intent": "COLOR_GALLERY",
                        "dialog_phase": state.get("dialog_phase", "ACTIVE"),
                        "messages": [{"role": "assistant", "content": str(agent_response_payload)}],
                        "metadata": metadata_update,
                        "selected_products": state.get("selected_products", []) or [],
                        "should_escalate": False,
                        "escalation_reason": None,
                        "step_number": state.get("step_number", 0) + 1,
                        "agent_response": agent_response_payload,
                    }
    except Exception as e:
        # If color gallery logic fails, continue with normal flow
        logger.debug("Color gallery check failed (non-critical): %s", e)
        pass

    if settings.DEBUG_TRACE_LOGS:
        debug_log.node_entry(
            session_id=session_id,
            node_name="agent",
            phase=state.get("dialog_phase", "?"),
            state_name=current_state,
            extra={"intent": state.get("detected_intent"), "msg": user_message},
        )

    # =========================================================================
    # HISTORY TRIMMER
    # =========================================================================
    from src.services.core.history_trimmer import trim_message_history

    original_messages = state.get("messages", [])
    trimmed_messages = trim_message_history(original_messages)
    state_for_llm = {**state, "messages": trimmed_messages}

    deps = create_deps_from_state(state_for_llm)

    # =========================================================================
    # STATE PROMPTS
    # =========================================================================
    dialog_phase = state.get("dialog_phase", "INIT")
    state_prompt = get_state_prompt(current_state)

    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        payment_sub = get_payment_sub_phase(state)
        state_prompt = get_state_prompt(current_state, payment_sub)

    if state_prompt:
        deps.state_specific_prompt = state_prompt

    try:
        # LLM CALL
        # NOTE: We deliberately call `run_support` via the package-level symbol
        # so tests can patch `src.agents.langgraph.nodes.agent.run_support`.
        from src.agents.langgraph.nodes import agent as agent_pkg

        response: SupportResponse = await agent_pkg.run_support(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        logger.info(
            "Agent response for session %s: event=%s, state=%s->%s, intent=%s",
            session_id,
            response.event,
            current_state,
            response.metadata.current_state,
            response.metadata.intent,
        )
        
        # Cleanup greeting if repeated (Vision node quirk)
        vision_greeted_before = bool(state.get("metadata", {}).get("vision_greeted", False))
        if (
            current_state == State.STATE_3_SIZE_COLOR.value
            and vision_greeted_before
            and response.messages
            and len(response.messages) > 1
        ):
            first_content = response.messages[0].content.strip().lower()
            data = load_yaml_from_registry(SystemKeys.TEXTS.value)
            greetings = []
            if isinstance(data, dict):
                greetings = data.get("greetings", {}).get("ua_keywords", [])
            if any(gr in first_content for gr in greetings):
                response.messages = response.messages[1:]

        # =====================================================================
        # POST-PROCESSING
        # =====================================================================
        intent = response.metadata.intent
        new_state_str = response.metadata.current_state
        is_escalation = response.event == "escalation"
        
        # Payment Override check
        new_state_str, changed = logic.check_payment_override(
            current_state, dialog_phase, intent, new_state_str
        )
        if changed:
            response.metadata.current_state = new_state_str
            if intent != "PAYMENT_DELIVERY":
                intent = "PAYMENT_DELIVERY"
                response.metadata.intent = "PAYMENT_DELIVERY"

        # Product Merging & Upsell
        selected_products = state.get("selected_products", [])
        if response.products:
            new_products = [p.model_dump() for p in response.products]
            upsell_flow_active = bool(state.get("metadata", {}).get("upsell_flow_active"))
            
            should_append = logic.should_trigger_upsell(
                selected_products,
                current_state=current_state,
                next_state=new_state_str,
                upsell_flow_active=upsell_flow_active,
            )
            
            if should_append:
                # Upsell Logic
                metadata_flags = state.get("metadata", {}) or {}
                upsell_base_products = metadata_flags.get("upsell_base_products") or []
                
                base_products = selected_products
                used_upsell_base = False
                
                if not base_products and upsell_base_products:
                    base_products = upsell_base_products
                    used_upsell_base = True
                    
                selected_products = tools.merge_products(
                    base_products, new_products, append=True
                )
                
                # Cleanup duplicates if we inserted base products
                if used_upsell_base:
                     new_keys = {
                        tools.product_match_key(p) for p in new_products if tools.product_match_key(p)
                    }
                     if new_keys:
                        selected_products = [
                            p for p in selected_products if tools.product_match_key(p) in new_keys
                        ] + [p for p in selected_products if tools.product_match_key(p) not in new_keys]

            else:
                # Normal replace
                selected_products = tools.merge_products(
                    selected_products, new_products, append=False
                )

        # Size Extraction Fallback
        if selected_products and current_state == State.STATE_3_SIZE_COLOR.value:
            first_product = selected_products[0]
            if not first_product.get("size"):
                extracted_size = tools.extract_size_from_response(response.messages)
                if extracted_size:
                    first_product["size"] = extracted_size
            
            # Copy color from vision
            if not first_product.get("color") and state.get("identified_color"):
                first_product["color"] = state.get("identified_color")

        # Height Application
        height_in_text = extract_height_from_text(user_message)
        height_from_context = height_in_text or state.get("metadata", {}).get("height_cm")
        if height_from_context and selected_products:
            selected_products = tools.apply_height_to_products(selected_products, height_from_context)

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log
        log_agent_step(
            session_id=session_id,
            state=new_state_str,
            intent=intent,
            event=response.event,
            latency_ms=latency_ms,
            extra={
                "products_count": len(selected_products),
            },
        )
        track_metric("agent_node_latency_ms", latency_ms)

        # Update Metadata
        metadata_update = state.get("metadata", {}).copy()
        metadata_update["current_state"] = new_state_str
        metadata_update["intent"] = intent
        
        if height_in_text:
            metadata_update["height_cm"] = height_in_text
            
        if response.customer_data:
            # Copy customer fields... skipping specific field loop for brevity, generic update
            if response.customer_data.name: metadata_update["customer_name"] = response.customer_data.name
            if response.customer_data.phone: metadata_update["customer_phone"] = response.customer_data.phone
            if response.customer_data.city: metadata_update["customer_city"] = response.customer_data.city
            if response.customer_data.nova_poshta: metadata_update["customer_nova_poshta"] = response.customer_data.nova_poshta

        if response.products:
            # Disable upsell flag if we just handled it
             if bool(state.get("metadata", {}).get("upsell_flow_active")):
                  metadata_update["upsell_flow_active"] = False

        # =====================================================
        # DIALOG PHASE
        # =====================================================
        dialog_phase = logic.determine_phase(
            current_state=new_state_str,
            event=response.event,
            selected_products=selected_products,
            metadata=response.metadata,
            state=state,
        )
        
        # State override if needed
        if (
            dialog_phase == "DISCOVERY"
            and new_state_str == State.STATE_2_VISION.value
            and not selected_products
        ):
             new_state_str = State.STATE_1_DISCOVERY.value
             response.metadata.current_state = new_state_str
             metadata_update["current_state"] = new_state_str

        # Validate Transition
        new_state_str = logic.validate_fsm_transition(dialog_phase, new_state_str, session_id)
        response.metadata.current_state = new_state_str
        metadata_update["current_state"] = new_state_str

        assistant_content = {
            "event": response.event,
            "messages": [m.model_dump() for m in response.messages],
            "products": [p.model_dump() for p in response.products],
            "metadata": response.metadata.model_dump(),
        }
        
        if response.escalation:
            assistant_content["escalation"] = response.escalation.model_dump()
        if response.reasoning:
            assistant_content["reasoning"] = response.reasoning

        agent_response_payload = response.model_dump()

        # Async Trace Logging success
        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="agent_node",
            status="SUCCESS",
            state_name=new_state_str,
            output_snapshot=assistant_content,
            latency_ms=latency_ms,
        )

        return {
            "current_state": new_state_str,
            "detected_intent": intent,
            "dialog_phase": dialog_phase,
            "messages": [{"role": "assistant", "content": str(assistant_content)}],
            "metadata": metadata_update,
            "selected_products": selected_products,
            "should_escalate": is_escalation,
            "escalation_reason": response.escalation.reason if response.escalation else None,
            "step_number": state.get("step_number", 0) + 1,
            "agent_response": agent_response_payload,
        }

    except Exception as e:
        logger.error("Agent node failed for session %s: %s", session_id, e)
        if span:
            span.set_attribute("error", True)
            span.set_attribute("error_type", type(e).__name__)
            span.set_attribute("error_message", str(e)[:200])
        await log_trace(
             session_id=session_id, trace_id=trace_id, node_name="agent_node",
             status="ERROR", error_message=str(e), state_name=current_state
        )
        return {
            "last_error": str(e),
            "tool_errors": [*state.get("tool_errors", []), f"Agent error: {e}"],
            "retry_count": state.get("retry_count", 0) + 1,
            "step_number": state.get("step_number", 0) + 1,
        }
    finally:
        if span:
            span.end()
