"""
Dependencies - Dependency Injection for agents.
==============================================
Central context container passed to agent.run(...) as ctx.deps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from src.services.data.catalog_service import CatalogService
    from src.services.data.order_service import OrderService
    from src.services.domain.memory.memory_service import MemoryService
    from src.services.domain.vision.vision_context import VisionContextService

    from .models import StateType


if TYPE_CHECKING:
    Database = OrderService
else:
    Database = Any


@dataclass(init=False)
class AgentDeps:
    """
    Main dependencies container for PydanticAI agents.

    Usage:
        deps = AgentDeps(
            session_id="user_123",
            user_id="manychat_456",
            db=Database(),
            catalog=CatalogService(),
        )
        result = await agent.run(message, deps=deps)
    """

    session_id: str
    user_id: str = ""
    trace_id: str = ""

    current_state: StateType = "STATE_0_INIT"
    channel: str = "instagram"
    language: str = "uk"

    # Image context
    has_image: bool = False
    image_url: str | None = None

    # Product context
    selected_products: list[dict[str, Any]] = field(default_factory=list)

    # Customer data
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_city: str | None = None
    customer_nova_poshta: str | None = None

    # Memory context (optional, provided by LangGraph)
    memory_context_prompt: str | None = None
    memory_profile: Any = None
    memory_facts: list[Any] = field(default_factory=list)

    env: str = "production"

    _db: Any = field(default=None, repr=False)
    _catalog: Any = field(default=None, repr=False)
    _memory: Any = field(default=None, repr=False)
    _vision: Any = field(default=None, repr=False)

    def __init__(
        self,
        session_id: str,
        user_id: str = "",
        trace_id: str = "",
        current_state: StateType = "STATE_0_INIT",
        channel: str = "instagram",
        language: str = "uk",
        has_image: bool = False,
        image_url: str | None = None,
        selected_products: list[dict[str, Any]] | None = None,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        customer_city: str | None = None,
        customer_nova_poshta: str | None = None,
        memory_context_prompt: str | None = None,
        memory_profile: Any = None,
        memory_facts: list[Any] | None = None,
        db: Any = None,
        catalog: Any = None,
        memory: Any = None,
        vision: Any = None,
        env: str = "production",
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.trace_id = trace_id
        self.current_state = current_state
        self.channel = channel
        self.language = language
        self.has_image = has_image
        self.image_url = image_url
        self.selected_products = selected_products or []
        self.customer_name = customer_name
        self.customer_phone = customer_phone
        self.customer_city = customer_city
        self.customer_nova_poshta = customer_nova_poshta
        self.memory_context_prompt = memory_context_prompt
        self.memory_profile = memory_profile
        self.memory_facts = memory_facts or []
        self._db = db
        self._catalog = catalog
        self._memory = memory
        self._vision = vision
        self.env = env

    @property
    def db(self) -> "OrderService":
        if self._db is None:
            from src.services.data.order_service import OrderService

            # SAFEGUARD_1: Log creation of heavy clients (network connections)
            logger.info(
                "[AGENT_DEPS] Creating OrderService (lazy loading) for session=%s",
                self.session_id,
            )
            self._db = OrderService()
            # SAFEGUARD_2: Verify singleton (check if same instance)
            logger.debug(
                "[AGENT_DEPS] OrderService created: id=%s",
                id(self._db),
            )
        return self._db

    @property
    def catalog(self) -> "CatalogService":
        if self._catalog is None:
            from src.services.data.catalog_service import CatalogService

            # SAFEGUARD_1: Log creation of heavy clients (network connections)
            logger.info(
                "[AGENT_DEPS] Creating CatalogService (lazy loading) for session=%s",
                self.session_id,
            )
            self._catalog = CatalogService()
            # SAFEGUARD_2: Verify singleton (check if same instance)
            logger.debug(
                "[AGENT_DEPS] CatalogService created: id=%s",
                id(self._catalog),
            )
        return self._catalog

    @property
    def memory(self) -> "MemoryService":
        if self._memory is None:
            from src.services.domain.memory.memory_service import MemoryService

            # SAFEGUARD_1: Log creation of heavy clients (network connections)
            logger.info(
                "[AGENT_DEPS] Creating MemoryService (lazy loading) for session=%s",
                self.session_id,
            )
            self._memory = MemoryService()
            # SAFEGUARD_2: Verify singleton (check if same instance)
            logger.debug(
                "[AGENT_DEPS] MemoryService created: id=%s",
                id(self._memory),
            )
        return self._memory

    @property
    def vision(self) -> "VisionContextService":
        if self._vision is None:
            from src.services.domain.vision.vision_context import VisionContextService

            # SAFEGUARD_1: Log creation of heavy clients (network connections)
            logger.info(
                "[AGENT_DEPS] Creating VisionContextService (lazy loading) for session=%s",
                self.session_id,
            )
            self._vision = VisionContextService(self.catalog)
            # SAFEGUARD_2: Verify singleton (check if same instance)
            logger.debug(
                "[AGENT_DEPS] VisionContextService created: id=%s",
                id(self._vision),
            )
        return self._vision

    def get_customer_data_summary(self) -> str:
        """Get summary of collected customer data for prompts."""
        from src.services.domain.payment.payment_config import get_payment_section

        labels = get_payment_section("order_context")
        label_name = labels.get("label_name", "Full name")
        label_phone = labels.get("label_phone", "Phone")
        label_city = labels.get("label_city", "City")
        label_branch = labels.get("label_branch", "Branch")
        empty_text = labels.get("no_data", "No customer data collected.")

        data = []
        if self.customer_name:
            data.append(f"{label_name}: {self.customer_name}")
        if self.customer_phone:
            data.append(f"{label_phone}: {self.customer_phone}")
        if self.customer_city:
            data.append(f"{label_city}: {self.customer_city}")
        if self.customer_nova_poshta:
            data.append(f"{label_branch}: {self.customer_nova_poshta}")

        if not data:
            return empty_text
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


def create_deps_from_state(state: dict[str, Any]) -> AgentDeps:
    """Create AgentDeps from LangGraph state."""
    from src.app.bootstrap import build_agent_deps

    return build_agent_deps(state)


def create_mock_deps(session_id: str = "test_session") -> AgentDeps:
    """Create mock deps for testing."""
    return AgentDeps(
        session_id=session_id,
        user_id="test_user",
        env="test",
    )
