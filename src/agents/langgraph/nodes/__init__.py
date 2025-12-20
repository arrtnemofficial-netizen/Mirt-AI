"""
LangGraph Nodes - Individual processing units.
==============================================
Each node is a pure function: state in -> state update out.

Memory System (Titans-like):
- memory_context_node: loads profile + facts BEFORE agents
- memory_update_node: silently updates memory AFTER key states
"""

from .agent import agent_node
from .crm_error import crm_error_node
from .escalation import escalation_node
from .intent import intent_detection_node
from .memory import (
    memory_context_node,
    memory_update_node,
    should_load_memory,
    should_update_memory,
)
from .moderation import moderation_node
from .offer import offer_node
from .payment import payment_node
from .sitniks_status import (
    STAGE_ESCALATION,
    STAGE_FIRST_TOUCH,
    STAGE_GIVE_REQUISITES,
    determine_stage,
    sitniks_pre_response_node,
    sitniks_status_node,
)
from .upsell import upsell_node
from .validation import validation_node
from .vision import vision_node


__all__ = [
    "moderation_node",
    "intent_detection_node",
    "vision_node",
    "agent_node",
    "offer_node",
    "payment_node",
    "upsell_node",
    "escalation_node",
    "validation_node",
    "crm_error_node",
    # Memory System
    "memory_context_node",
    "memory_update_node",
    "should_load_memory",
    "should_update_memory",
    # Sitniks CRM Status Integration
    "sitniks_pre_response_node",
    "sitniks_status_node",
    "determine_stage",
    "STAGE_FIRST_TOUCH",
    "STAGE_GIVE_REQUISITES",
    "STAGE_ESCALATION",
]
