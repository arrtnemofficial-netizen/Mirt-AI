"""
PydanticAI Agents - Production Grade.
=====================================
This is the "sniper rifle" inside your LangGraph orchestra.

Structure:
- deps.py: Dependency Injection (DB, user context, etc.)
- models.py: Structured output models (type-safe responses)
- support_agent.py: Main sales/support agent
- vision_agent.py: Photo recognition specialist
- payment_agent.py: Payment flow specialist

Integration with LangGraph:
- LangGraph nodes call agent.run(message, deps=deps)
- Agents return typed Pydantic models
- Nodes update graph state based on agent output
"""

from .deps import AgentDeps, CatalogService, Database, create_deps_from_state
from .models import (
    CustomerDataExtracted,
    EscalationInfo,
    EscalationLevel,
    EventType,
    # Types (from OUTPUT_CONTRACT)
    IntentType,
    MessageItem,
    PaymentResponse,
    # Models
    ProductMatch,
    ResponseMetadata,
    StateType,
    SupportResponse,
    VisionResponse,
)
from .observability import configure_logfire, setup_observability
from .payment_agent import get_payment_agent, run_payment
from .support_agent import get_support_agent, run_support
from .vision_agent import get_vision_agent, run_vision


__all__ = [
    # Dependencies
    "AgentDeps",
    "Database",
    "CatalogService",
    "create_deps_from_state",
    # Type Literals (OUTPUT_CONTRACT)
    "IntentType",
    "StateType",
    "EventType",
    "EscalationLevel",
    # Models (OUTPUT_CONTRACT)
    "ProductMatch",
    "MessageItem",
    "ResponseMetadata",
    "EscalationInfo",
    "CustomerDataExtracted",
    "SupportResponse",
    "VisionResponse",
    "PaymentResponse",
    # Agent factories (lazy initialization)
    "get_support_agent",
    "get_vision_agent",
    "get_payment_agent",
    # Runners (what LangGraph nodes call)
    "run_support",
    "run_vision",
    "run_payment",
    # Observability
    "setup_observability",
    "configure_logfire",
]
