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


# =============================================================================
# DATABASE SERVICE (Mock for now, real Supabase in production)
# =============================================================================


@dataclass
class Database:
    """
    Database service for agent tools.

    In production: connects to Supabase/PostgreSQL.
    In tests: use mock implementation.
    """

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Get user profile from database."""
        # TODO: Replace with real Supabase query
        # from src.services.supabase_client import get_supabase_client
        # client = get_supabase_client()
        # return client.table("users").select("*").eq("id", user_id).single().execute()
        return {
            "id": user_id,
            "name": "Клієнт",
            "phone": None,
            "city": None,
        }

    async def get_user_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Get user's order history."""
        return []

    async def save_order(self, order_data: dict[str, Any]) -> str:
        """Save new order to database."""
        # Returns order ID
        return "order_123"


# =============================================================================
# CATALOG SERVICE
# =============================================================================


@dataclass
class CatalogService:
    """
    Product catalog service.

    Uses embedded catalog from system prompt.
    """

    async def search_products(
        self,
        query: str,
        category: str | None = None,
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search products in catalog."""
        # For now, returns empty - LLM uses embedded catalog
        # In future: could use vector search
        return []

    async def get_product_by_id(self, product_id: int) -> dict[str, Any] | None:
        """Get product details by ID."""
        return None

    async def get_size_recommendation(
        self,
        product_id: int,
        height_cm: int,
        age_years: int | None = None,
    ) -> str:
        """Get size recommendation based on height/age."""
        import bisect

        # Height thresholds and corresponding sizes
        thresholds = [80, 90, 100, 110, 120, 130, 140]
        sizes = ["68", "80", "92", "104", "116", "128", "140", "152"]

        index = bisect.bisect_left(thresholds, height_cm)
        return sizes[index]


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
    db: Database = field(default_factory=Database)
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
        return all([
            self.customer_name,
            self.customer_phone,
            self.customer_city,
            self.customer_nova_poshta,
            self.selected_products,
        ])


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
        user_id="test_user",
        env="test",
    )
