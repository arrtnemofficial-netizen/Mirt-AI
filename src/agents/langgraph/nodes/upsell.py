"""
Upsell Node - Additional sales opportunity.
==========================================
After payment confirmation, offer complementary products.
Uses run_main directly with upsell context.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

<<<<<<< Updated upstream
from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.support_agent import run_support
=======
from src.agents.langgraph.nodes.intent import get_intent_patterns
from src.agents.langgraph.state_prompts import detect_simple_intent
from src.agents.pydantic.deps import create_deps_from_state
from src.agents.pydantic.main_agent import run_main
from src.conf.config import settings
from src.core.debug_logger import debug_log
>>>>>>> Stashed changes
from src.core.state_machine import State
from src.services.core.observability import log_agent_step, track_metric


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents.pydantic.models import SupportResponse


logger = logging.getLogger(__name__)

<<<<<<< Updated upstream
=======
_UPSELL_DECLINE = (
    "нет",
    "ні",
    "не потрібно",
    "не треба",
    "не хочу",
    "не цікаво",
    "не интересует",
    "не интересна",
)


def _contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    return any(k in text for k in keywords)


def _should_restart_flow(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False
    if _contains_any(text, _UPSELL_DECLINE):
        return False
        
    # Lazy load patterns
    patterns = get_intent_patterns()
    upsell_confirmation = patterns.get("CONFIRMATION", [])
    
    if _contains_any(text, upsell_confirmation):
        return False
    intent_hint = detect_simple_intent(text)
    return intent_hint in {
        "REQUEST_PHOTO",
        "PRODUCT_CATEGORY",
        "DISCOVERY_OR_QUESTION",
        "SIZE_HELP",
        "COLOR_HELP",
    }


from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header


def _get_snippet_text(header: str, default: str) -> str:
    """Helper to get snippet text from registry."""
    bubbles = get_snippet_by_header(header)
    return "\n---\n".join(bubbles) if bubbles else default


def _build_crm_status_message(state: dict[str, Any]) -> str:
    """Build CRM status message for user display."""
    crm_order_result = state.get("crm_order_result", {})

    if not crm_order_result:
        return ""

    status = crm_order_result.get("status", "unknown")
    crm_order_id = crm_order_result.get("crm_order_id")
    task_id = crm_order_result.get("task_id")

    if status == "queued":
        message = _get_snippet_text("UPSELL_CRM_QUEUED", "🔄 Замовлення відправлено до CRM системи")
        if task_id:
            message = message.replace("CRM системи", f"CRM системи (завдання #{task_id[:8]}...)")
    elif status == "created":
        message = _get_snippet_text("UPSELL_CRM_CREATED", "✅ Замовлення успішно створено в CRM")
        if crm_order_id:
            message += f" (№{crm_order_id})"
    elif status == "exists":
        message = _get_snippet_text("UPSELL_CRM_EXISTS", "ℹ️ Замовлення вже існує в CRM")
        if crm_order_id:
            message += f" (№{crm_order_id})"
    elif status == "failed":
        error = crm_order_result.get("error", "Невідома помилка")
        message = _get_snippet_text("UPSELL_CRM_FAILED", "⚠️ Проблема з створенням замовлення в CRM: {error}").format(error=error)
    else:
        message = f"📋 Статус замовлення в CRM: {status}"

    return message

>>>>>>> Stashed changes

async def upsell_node(
    state: dict[str, Any],
    runner: Callable[..., Any] | None = None,  # Kept for signature compatibility
) -> dict[str, Any]:
    """
    Offer additional products after payment confirmation.

    This is a soft upsell - suggest, don't push.

    Args:
        state: Current conversation state
        runner: IGNORED - uses run_main directly

    Returns:
        State update with upsell response
    """
    start_time = time.perf_counter()
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))

    # Get user message (handles both dict and LangChain Message objects)
    from .utils import extract_user_message
    user_message = extract_user_message(state.get("messages", []))
    if not user_message:
        user_message = "Completed"

    # Get current order for context
    ordered_products = state.get("offered_products", []) or state.get("selected_products", [])

<<<<<<< Updated upstream
=======
    # Check CRM order status and build status message
    crm_status_message = _build_crm_status_message(state)

    if _should_restart_flow(user_message):
        restart_text = _get_snippet_text("UPSELL_RESTART", "Супер! Давайте підберемо ще одну модель 🌸")
        metadata_update = state.get("metadata", {}).copy()
        metadata_update.update(
            {
                "current_state": State.STATE_1_DISCOVERY.value,
                "intent": "DISCOVERY_OR_QUESTION",
                "upsell_flow_active": True,
                "upsell_base_products": ordered_products,
            }
        )
        return {
            "current_state": State.STATE_1_DISCOVERY.value,
            "messages": [{"role": "assistant", "content": restart_text}],
            "metadata": metadata_update,
            "selected_products": [],
            "offered_products": [],
            "agent_response": {
                "event": "simple_answer",
                "messages": [{"type": "text", "content": restart_text}],
                "metadata": {
                    "session_id": session_id,
                    "current_state": State.STATE_1_DISCOVERY.value,
                    "intent": "DISCOVERY_OR_QUESTION",
                    "escalation_level": "NONE",
                },
            },
            "dialog_phase": "DISCOVERY",
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

>>>>>>> Stashed changes
    # Create deps with upsell context
    deps = create_deps_from_state(state)
    deps.current_state = State.STATE_6_UPSELL.value
    deps.selected_products = ordered_products

    logger.info("Upsell node for session %s", session_id)

    try:
        # Call support agent with upsell context
        response: SupportResponse = await run_main(
            message=user_message,
            deps=deps,
            message_history=None,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        log_agent_step(
            session_id=session_id,
            state=State.STATE_6_UPSELL.value,
            intent=response.metadata.intent,
            event=response.event,
            latency_ms=latency_ms,
        )
        track_metric("upsell_node_latency_ms", latency_ms)
        track_metric("upsell_offered", 1, {"session_id": session_id})

        # Build assistant message from response
        assistant_content = "\n".join(m.content for m in response.messages)

        return {
            "current_state": State.STATE_6_UPSELL.value,
            "messages": [{"role": "assistant", "content": assistant_content}],
            "metadata": response.metadata.model_dump(),
            "agent_response": response.model_dump(),
            "step_number": state.get("step_number", 0) + 1,
            "last_error": None,
        }

    except Exception as e:
        logger.exception("Upsell node failed for session %s: %s", session_id, e)

        # Non-critical - just skip upsell on error
        return {
            "current_state": State.STATE_7_END.value,
            "step_number": state.get("step_number", 0) + 1,
        }
