"""
Dependencies - Dependency Injection для агентів.
================================================
ПРАВИЛО №1: Ніколи не хардкодь ключі API, з'єднання з БД чи ID юзера!

Все передається через ctx.deps:
- Тестування: підсунь мок-об'єкт замість реальної БД
- Безпека: ніяких глобальних змінних
- Чистота: кожен виклик ізольований

Memory System (Titans-like):
- memory: MemoryService для роботи з памʼяттю
- profile: UserProfile з Persistent Memory
- facts: list[Fact] з Fluid Memory
- memory_context_prompt: форматований контекст для промпта
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .memory_models import Fact, UserProfile
    from .models import StateType


logger = logging.getLogger(__name__)


from src.services.catalog_service import CatalogService
from src.services.memory_service import MemoryService
from src.services.order_service import OrderService


# =============================================================================
# DATABASE SERVICE (PostgreSQL Implementation)
# =============================================================================

# We use OrderService as the main database interface for agents
Database = OrderService

# =============================================================================
# CATALOG SERVICE (PostgreSQL Implementation)
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
            memory=MemoryService(),
        )
        result = await agent.run(message, deps=deps)
    """

    # Session identification
    session_id: str
    trace_id: str  # For distributed tracing of this specific request
    user_id: str = ""
    user_nickname: str | None = None

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

    # Payment flow (STATE_5_PAYMENT_DELIVERY) sub-phase hint for prompt injection
    payment_sub_phase: str | None = None

    # Services (injected)
    db: OrderService = field(default_factory=OrderService)
    catalog: CatalogService = field(default_factory=CatalogService)
    memory: MemoryService | None = None  # Lazy init to avoid circular import

    # Environment
    env: str = "production"

    # State-specific prompt (injected by agent_node for Turn-Based routing)
    # Contains detailed instructions for current state (e.g., STATE_4_OFFER prompt)
    state_specific_prompt: str | None = None

    # ==========================================================================
    # MEMORY SYSTEM (Titans-like)
    # ==========================================================================
    # These are populated by memory_context_node before agent execution

    # Persistent Memory - user profile (always loaded)
    profile: UserProfile | None = None

    # Fluid Memory - relevant facts (top-K by importance)
    facts: list[Fact] = field(default_factory=list)

    # Pre-formatted memory context for prompt injection
    memory_context_prompt: str | None = None

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

    def get_memory_context_prompt(self) -> str:
        """
        Get formatted memory context for prompt injection.

        Returns pre-formatted string or generates from profile/facts.
        """
        # Use pre-formatted if available (set by memory_context_node)
        if self.memory_context_prompt:
            return self.memory_context_prompt

        # Generate from profile and facts
        lines = []

        if self.profile:
            p = self.profile

            # Child info
            if hasattr(p, "child_profile") and p.child_profile:
                child = p.child_profile
                child_info = []
                if hasattr(child, "name") and child.name:
                    child_info.append(f"імʼя: {child.name}")
                if hasattr(child, "age") and child.age:
                    child_info.append(f"вік: {child.age}")
                if hasattr(child, "height_cm") and child.height_cm:
                    child_info.append(f"зріст: {child.height_cm} см")
                if hasattr(child, "gender") and child.gender:
                    child_info.append(f"стать: {child.gender}")
                if child_info:
                    lines.append(f"Дитина: {', '.join(child_info)}")

            # Logistics from profile
            if hasattr(p, "logistics") and p.logistics:
                if hasattr(p.logistics, "city") and p.logistics.city:
                    lines.append(f"Місто: {p.logistics.city}")
                if hasattr(p.logistics, "favorite_branch") and p.logistics.favorite_branch:
                    lines.append(f"НП: {p.logistics.favorite_branch}")

            # Style preferences
            if hasattr(p, "style_preferences") and p.style_preferences:
                if (
                    hasattr(p.style_preferences, "favorite_models")
                    and p.style_preferences.favorite_models
                ):
                    lines.append(
                        f"Улюблені моделі: {', '.join(p.style_preferences.favorite_models)}"
                    )

        # Add facts
        if self.facts:
            fact_lines = [f"- {f.content}" for f in self.facts[:5]]
            if fact_lines:
                lines.append("Факти: " + "; ".join(f.content for f in self.facts[:5]))

        if not lines:
            return ""

        return "### ЩО МИ ЗНАЄМО ПРО КЛІЄНТА:\n" + "\n".join(lines)

    def has_memory_context(self) -> bool:
        """Check if any memory context is available."""
        return bool(self.profile or self.facts or self.memory_context_prompt)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_deps_from_state(state: dict[str, Any]) -> AgentDeps:
    """
    Create AgentDeps from LangGraph state.

    This is the bridge between LangGraph and PydanticAI.

    Memory fields (profile, facts, memory_context_prompt) are populated
    by memory_context_node before agent execution.
    """
    metadata = state.get("metadata", {})

    payment_sub_phase: str | None = None
    try:
        if state.get("current_state") == "STATE_5_PAYMENT_DELIVERY":
            from src.agents.langgraph.state_prompts import get_payment_sub_phase

            payment_sub_phase = get_payment_sub_phase(state)
    except Exception:
        payment_sub_phase = None

    return AgentDeps(
        session_id=state.get("session_id", metadata.get("session_id", "")),
        trace_id=state.get("trace_id", ""),  # Must be populated by graph
        user_id=metadata.get("user_id", ""),
        user_nickname=metadata.get("user_nickname"),
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
        payment_sub_phase=payment_sub_phase,
        # Memory system fields (populated by memory_context_node)
        profile=state.get("memory_profile"),
        facts=state.get("memory_facts", []),
        memory_context_prompt=state.get("memory_context_prompt"),
    )


def create_mock_deps(session_id: str = "test_session") -> AgentDeps:
    """Create mock deps for testing."""
    return AgentDeps(
        session_id=session_id,
        trace_id="mock_trace_id",
        user_id="test_user",
        env="test",
    )


async def create_deps_with_memory(
    state: dict[str, Any],
    memory_service: MemoryService | None = None,
) -> AgentDeps:
    """
    Create AgentDeps with memory context loaded.

    This is an async version that loads memory from PostgreSQL.
    Use this when memory_context_node hasn't run yet.

    Args:
        state: LangGraph state
        memory_service: Optional MemoryService (creates one if not provided)

    Returns:
        AgentDeps with profile and facts loaded
    """
    deps = create_deps_from_state(state)

    if not deps.user_id:
        return deps

    # Get or create memory service
    if memory_service is None:
        memory_service = MemoryService()

    if not memory_service.enabled:
        return deps

    # Load memory context
    try:
        context = await memory_service.load_memory_context(deps.user_id)
        deps.profile = context.profile
        deps.facts = context.facts
        deps.memory_context_prompt = context.to_prompt_block()
    except Exception as e:
        logger.warning("Failed to load memory context for user %s: %s", deps.user_id, e)

    return deps
