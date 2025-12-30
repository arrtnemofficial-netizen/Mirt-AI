# helpers/payment/approval.py
"""
HITL approval response handler.
Extracted from payment.py for modularity.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.types import Command

from src.core.state_machine import State
from src.services.observability import log_agent_step, track_metric

from .crm import persist_order_and_queue_crm

logger = logging.getLogger(__name__)


async def handle_approval_response(
    state: dict[str, Any],
    session_id: str,
) -> Command[Literal["upsell", "end", "validation"]]:
    """Handle the human's approval response."""

    approved = state.get("human_approved")
    approval_data = state.get("approval_data", {})
    trace_id = state.get("trace_id", "")

    log_agent_step(
        session_id=session_id,
        state=State.STATE_5_PAYMENT_DELIVERY.value,
        intent="PAYMENT_DELIVERY",
        event="payment_approval",
        extra={
            "trace_id": trace_id,
            "approved": approved,
            "total_price": approval_data.get("total_price"),
        },
    )

    if approved:
        # Payment approved - proceed to upsell
        logger.info("Payment APPROVED for session %s", session_id)
        track_metric("payment_approved", 1, {"session_id": session_id})

        # =========================================================================
        # CRITICAL: Payment Proof Guard (HITL flow)
        # =========================================================================
        from src.agents.langgraph.rules.payment_proof import detect_payment_proof
        from src.agents.langgraph.nodes.utils import extract_user_message

        user_message = extract_user_message(state.get("messages", []))
        has_image = bool(
            state.get("has_image", False) or state.get("metadata", {}).get("has_image", False)
        )
        has_url = bool(
            user_message
            and ("http://" in user_message.lower() or "https://" in user_message.lower())
        )

        has_real_proof = detect_payment_proof(
            user_text=user_message or "",
            has_image=has_image,
            has_url=has_url,
        )

        if not has_real_proof:
            # HITL approved, але payment proof не отримано - чекаємо proof
            logger.warning(
                "[SESSION %s] HITL approved but no payment proof detected. Waiting for proof.",
                session_id,
            )
            return Command(
                update={
                    "awaiting_human_approval": False,
                    "approval_type": None,
                    "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                    "dialog_phase": "WAITING_FOR_PAYMENT_PROOF",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "Надішліть, будь ласка, скрін або квитанцію оплати 🤍",
                        }
                    ],
                    "agent_response": {
                        "event": "simple_answer",
                        "messages": [
                            {
                                "type": "text",
                                "content": "Надішліть, будь ласка, скрін або квитанцію оплати 🤍",
                            }
                        ],
                        "metadata": {
                            "session_id": session_id,
                            "current_state": State.STATE_5_PAYMENT_DELIVERY.value,
                            "intent": "PAYMENT_DELIVERY",
                            "escalation_level": "NONE",
                        },
                    },
                    "step_number": state.get("step_number", 0) + 1,
                },
                goto="end",
            )

        # =========================================================================
        # SAVE ORDER TO DB (Persistence)
        # =========================================================================
        crm_order_result = await persist_order_and_queue_crm(
            state=state,
            session_id=session_id,
            approval_data=approval_data,
        )

        # DIALOG PHASE: UPSELL_OFFERED (STATE_6)
        return Command(
            update={
                "awaiting_human_approval": False,
                "approval_type": None,
                "current_state": State.STATE_6_UPSELL.value,
                "dialog_phase": "UPSELL_OFFERED",
                "crm_order_result": crm_order_result,
                "crm_external_id": crm_order_result.get("external_id")
                if crm_order_result
                else None,
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="upsell",
        )
    else:
        # Payment rejected - back to offer
        logger.info("Payment REJECTED for session %s", session_id)
        track_metric("payment_rejected", 1, {"session_id": session_id})

        # DIALOG PHASE: OFFER_MADE (повертаємо до STATE_4)
        return Command(
            update={
                "awaiting_human_approval": False,
                "approval_type": None,
                "human_approved": None,
                "current_state": State.STATE_4_OFFER.value,
                "dialog_phase": "OFFER_MADE",
                "step_number": state.get("step_number", 0) + 1,
            },
            goto="end",
        )
