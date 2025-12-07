"""
Dependencies - Dependency Injection для агентів.
================================================
ПРАВИЛО №1: Ніколи не хардкодь ключі API, з'єднання з БД чи ID юзера!

Все передається через ctx.deps:
- Тестування: підсунь мок-об'єкт замість реальної БД
- Безпека: ніяких глобальних змінних
- Чистота: кожен виклик ізольований
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .models import StateType


logger = logging.getLogger(__name__)


from src.services.catalog_service import CatalogService
from src.services.order_service import OrderService


# =============================================================================
# DATABASE SERVICE (Real Supabase Implementation)
# =============================================================================

# We use OrderService as the main database interface for agents
Database = OrderService

# =============================================================================
# CATALOG SERVICE (Real Supabase Implementation)
# =============================================================================

# CatalogService is now imported directly from src.services.catalog_service


# =============================================================================
# MAIN DEPENDENCIES CONTAINER
# =============================================================================


@dataclass
class AgentDeps:
    """
    Main dependencies container for PydanticAI agents.

    This is what gets passed to ctx.deps in every tool and instruction.

    Usage:
        deps = AgentDeps(
            session_id="user_123",
            user_id="manychat_456",
            db=Database(),
            catalog=CatalogService(),
        )
        result = await agent.run(message, deps=deps)
    """

    # Session identification
    session_id: str
    trace_id: str  # For distributed tracing of this specific request
    user_id: str = ""

    # Current conversation state (Literal type from models)
    current_state: StateType = "STATE_0_INIT"
    channel: str = "instagram"  # instagram, telegram, web
    language: str = "uk"

    # Image context
    has_image: bool = False
    image_url: str | None = None

    # Product context (from previous steps)
    selected_products: list[dict[str, Any]] = field(default_factory=list)

    # Customer data (collected during conversation)
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_city: str | None = None
    customer_nova_poshta: str | None = None

    # Services (injected)
    db: OrderService = field(default_factory=OrderService)
    catalog: CatalogService = field(default_factory=CatalogService)

    # Environment
    env: str = "production"

    def get_customer_data_summary(self) -> str:
        """Get summary of collected customer data for prompts."""
        data = []
        if self.customer_name:
            data.append(f"Ім'я: {self.customer_name}")
        if self.customer_phone:
            data.append(f"Телефон: {self.customer_phone}")
        if self.customer_city:
            data.append(f"Місто: {self.customer_city}")
        if self.customer_nova_poshta:
            data.append(f"Відділення НП: {self.customer_nova_poshta}")

        if not data:
            return "Дані клієнта ще не зібрані."
        return "\n".join(data)

    def is_ready_for_order(self) -> bool:
        """Check if all required data is collected for order."""
        return all(
            [
                self.customer_name,
                self.customer_phone,
                self.customer_city,
                self.customer_nova_poshta,
                self.selected_products,
            ]
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_deps_from_state(state: dict[str, Any]) -> AgentDeps:
    """
    Create AgentDeps from LangGraph state.

    This is the bridge between LangGraph and PydanticAI.
    """
    metadata = state.get("metadata", {})

    return AgentDeps(
        session_id=state.get("session_id", metadata.get("session_id", "")),
        trace_id=state.get("trace_id", ""),  # Must be populated by graph
        user_id=metadata.get("user_id", ""),
        current_state=state.get("current_state", "STATE_0_INIT"),
        channel=metadata.get("channel", "instagram"),
        language=metadata.get("language", "uk"),
        has_image=state.get("has_image", False),
        image_url=state.get("image_url"),
        selected_products=state.get("selected_products", []),
        customer_name=metadata.get("customer_name"),
        customer_phone=metadata.get("customer_phone"),
        customer_city=metadata.get("customer_city"),
        customer_nova_poshta=metadata.get("customer_nova_poshta"),
    )


def create_mock_deps(session_id: str = "test_session") -> AgentDeps:
    """Create mock deps for testing."""
    return AgentDeps(
        session_id=session_id,
        trace_id="mock_trace_id",
        user_id="test_user",
        env="test",
    )
