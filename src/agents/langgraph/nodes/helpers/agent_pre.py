"""
Agent Pre-processing Helpers.
=============================
Handles logic BEFORE LLM execution:
- Policy/Snippet checks
- Color gallery requests
- Message history trimming
- State prompt injection
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from src.conf.config import settings
from src.core.debug_logger import debug_log
from src.core.state_machine import State
from src.agents.langgraph.nodes.helpers.policy_snippets import maybe_apply_snippet_policy
from src.agents.langgraph.fsm.transition_reducer import compute_transition
from src.agents.langgraph.fsm.policy import determine_response_policy
from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header
from src.agents.langgraph.state_prompts import get_state_prompt
from src.agents.pydantic.deps import create_deps_from_state
from src.services.conversation import trim_message_history
from src.services.observability import log_agent_step

logger = logging.getLogger(__name__)


def check_policy_snippets(
    state: dict[str, Any],
    user_message: str,
    session_id: str,
) -> dict[str, Any] | None:
    """
    Check if a policy snippet should override LLM execution.
    Returns state update if snippet found, None otherwise.
    """
    detected_intent = state.get("detected_intent")

    # 1. Check Predefined Snippets (e.g. "no" responses)
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

    # 2. Check SSOT Response Policy (Snippet-only responses)
    transition = compute_transition(
        state=state,
        intent=detected_intent or "DISCOVERY_OR_QUESTION",
        has_image=state.get("has_image", False) or state.get("metadata", {}).get("has_image", False),
        user_message=user_message,
    )

    response_policy = determine_response_policy(
        next_state=transition.next_state,
        payment_sub_phase=transition.payment_sub_phase,
        metadata=state.get("metadata", {}),
        session_id=session_id,
    )

    if response_policy.snippet_name and not response_policy.use_llm:
        snippets = get_snippet_by_header(response_policy.snippet_name)
        if snippets:
            snippet_text = "\n\n".join(snippets)

            metadata_update = state.get("metadata", {}).copy()
            if response_policy.snippet_sent_flag:
                metadata_update[response_policy.snippet_sent_flag] = True

            logger.info(
                "[SESSION %s] 🎯 Snippet-only response (no LLM): snippet=%s",
                session_id,
                response_policy.snippet_name,
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


def handle_color_gallery(
    state: dict[str, Any],
    user_message: str,
    current_state: str,
) -> dict[str, Any] | None:
    """
    Handle requests to show color gallery.
    Returns state update if handled, None otherwise.
    """
    try:
        from src.agents.langgraph.rules.color_request import (
            detect_color_show_request,
            get_current_color_for_exclusion,
            get_product_name_for_color_show,
        )

        is_color_request = detect_color_show_request(user_message)
        is_show_more = (
            user_message.lower().strip() in ["показати решту", "покажи решту", "так", "да", "ок"]
            and state.get("metadata", {}).get("color_gallery_offset") is not None
        )

        if not (is_color_request or is_show_more):
            return None

        product_name = get_product_name_for_color_show(state)
        if not product_name:
            return None

        from src.agents.langgraph.nodes.helpers.vision.product_colors import (
            get_color_photos_for_upsell,
        )

        exclude_color = get_current_color_for_exclusion(state)

        if is_show_more:
            metadata = state.get("metadata", {})
            offset = metadata.get("color_gallery_offset", 0)
            if metadata.get("color_gallery_product"):
                product_name = metadata.get("color_gallery_product")
            if metadata.get("color_gallery_exclude"):
                exclude_color = metadata.get("color_gallery_exclude")
        else:
            offset = 0

        color_photos, has_more = get_color_photos_for_upsell(
            product_name=product_name,
            exclude_color=exclude_color,
            max_photos=4,
            offset=offset,
        )

        if not color_photos:
            return None

        session_id = state.get("session_id", "")
        trace_id = state.get("trace_id", "")

        messages = []
        for color_photo in color_photos:
            if color_photo.get("photo_url"):
                messages.append({"type": "image", "content": color_photo["photo_url"]})

        metadata_update = state.get("metadata", {}).copy()
        if has_more:
            messages.append({"type": "text", "content": "Показати решту кольорів?"})
            metadata_update["color_gallery_offset"] = offset + len(color_photos)
            metadata_update["color_gallery_product"] = product_name
            if exclude_color:
                metadata_update["color_gallery_exclude"] = exclude_color
        else:
            metadata_update.pop("color_gallery_offset", None)
            metadata_update.pop("color_gallery_product", None)
            metadata_update.pop("color_gallery_exclude", None)

        agent_response_payload = {
            "event": "simple_answer",
            "messages": messages,
            "products": state.get("selected_products", []) or [],
            "metadata": {
                "session_id": session_id,
                "current_state": current_state,
                "intent": "COLOR_HELP",
                "escalation_level": "NONE",
            },
        }

        metadata_update["current_state"] = current_state
        metadata_update["intent"] = "COLOR_HELP"

        # Format for Assistant
        assistant_messages = []
        for msg in messages:
            if msg["type"] == "text":
                assistant_messages.append({"role": "assistant", "content": msg["content"]})
            elif msg["type"] == "image":
                assistant_messages.append({"role": "assistant", "type": "image", "content": msg["content"]})

        with suppress(Exception):
            log_agent_step(
                session_id=session_id,
                state=current_state,
                intent="COLOR_HELP",
                event="color_gallery_shown",
                latency_ms=0.0,
                extra={
                    "trace_id": trace_id,
                    "product_name": product_name,
                    "colors_shown": len(color_photos),
                },
            )

        return {
            "current_state": current_state,
            "detected_intent": "COLOR_HELP",
            "dialog_phase": state.get("dialog_phase", "WAITING_FOR_COLOR"),
            "messages": assistant_messages,
            "metadata": metadata_update,
            "selected_products": state.get("selected_products", []) or [],
            "should_escalate": False,
            "step_number": state.get("step_number", 0) + 1,
            "agent_response": agent_response_payload,
        }
    except Exception as e:
        logger.debug("Color show request handler error: %s", e)
        return None


def prepare_llm_dependencies(
    state: dict[str, Any],
    current_state: str,
    transition_data: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """
    Prepare Deps and State for LLM.
    Handles prompt injection and message trimming.
    """
    session_id = state.get("session_id", "")
    trace_id = state.get("trace_id", "")

    # Trim history
    original_messages = state.get("messages", [])
    trimmed_messages = trim_message_history(original_messages)
    state_for_llm = {**state, "messages": trimmed_messages}

    # Create Deps
    deps = create_deps_from_state(state_for_llm)

    # Inject State Prompt
    dialog_phase = state.get("dialog_phase", "INIT")

    # Special case for Payment Sub-phase
    # Logic moved from agent.py: use transition data if available
    payment_sub = None
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        if transition_data and transition_data.payment_sub_phase:
            payment_sub = transition_data.payment_sub_phase
        else:
            payment_sub = "REQUEST_DATA"  # Default fallback

    state_prompt = get_state_prompt(current_state, payment_sub)

    if state_prompt:
        deps.state_specific_prompt = state_prompt
        logger.debug("Injected state prompt for %s", current_state)

        if settings.DEBUG_TRACE_LOGS:
            debug_log.prompt_debug(
                session_id=session_id,
                prompt_name=f"state.{current_state}",
                prompt_content=state_prompt,
                variables={"dialog_phase": dialog_phase, "trace_id": trace_id},
            )

    return deps, state_for_llm
