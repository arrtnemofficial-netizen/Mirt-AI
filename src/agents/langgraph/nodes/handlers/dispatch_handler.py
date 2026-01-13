
"""
Dispatch Handler.
=================
Responsible for selecting and executing the correct Pydantic Agent.
Handles:
1. Routing (Support vs Payment agent).
2. Data Extraction (Customer Data from Payment Response).
3. Normalization (PaymentResponse -> SupportResponse).
"""

import logging
from typing import Any

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.models import (
    SupportResponse,
    MessageItem,
    ResponseMetadata,
)
from src.agents.pydantic.support_agent import run_support
from src.agents.pydantic.payment_agent import run_payment
from src.core.state_machine import State

logger = logging.getLogger(__name__)


async def execute_agent_dispatch(
    user_message: str,
    deps: AgentDeps,
    current_state: str,
    message_history: list[Any] | None = None,
) -> SupportResponse:
    """
    Execute the appropriate agent based on state.

    Args:
        user_message: User input.
        deps: Dependencies (injected).
        current_state: Current state Enum string.
        message_history: Optional history.

    Returns:
        Unified SupportResponse.
    """

    # 1. Payment Agent Dispatch
    if current_state == State.STATE_5_PAYMENT_DELIVERY.value:
        payment_response = await run_payment(
            message=user_message,
            deps=deps,
            message_history=message_history,
        )

        # Normalize to SupportResponse
        messages = [MessageItem(type="text", content=payment_response.reply_to_user)]

        # Build Metadata with intentional customer_data update
        metadata_dict = deps.metadata.model_dump() if hasattr(deps, 'metadata') else {}

        # Apply extracted customer data
        if payment_response.customer_data:
            c_data = payment_response.customer_data
            if c_data.name:
                metadata_dict["customer_name"] = c_data.name
            if c_data.phone:
                metadata_dict["customer_phone"] = c_data.phone
            if c_data.city:
                metadata_dict["customer_city"] = c_data.city
            if c_data.nova_poshta:
                metadata_dict["customer_nova_poshta"] = c_data.nova_poshta

        metadata = ResponseMetadata(
            session_id=metadata_dict.get("session_id", ""),
            current_state=State.STATE_5_PAYMENT_DELIVERY.value,
            intent="PAYMENT_DELIVERY",
            escalation_level="NONE",
        )

        response = SupportResponse(
            event="clarifying_question" if payment_response.missing_fields else "simple_answer",
            messages=messages,
            products=[],
            metadata=metadata,
        )

        # Attach raw customer_data for the transition handler (special field)
        response.customer_data = payment_response.customer_data
        return response

    # 2. Default Support Agent Dispatch
    else:
        return await run_support(
            message=user_message,
            deps=deps,
            message_history=message_history,
        )
