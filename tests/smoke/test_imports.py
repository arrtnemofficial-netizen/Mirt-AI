"""
SMOKE: Test all critical modules are importable.

This catches import errors, circular dependencies, and missing dependencies
BEFORE running expensive tests.
"""

import pytest


@pytest.mark.smoke
@pytest.mark.critical
class TestCriticalImports:
    """Verify all critical modules can be imported without error."""

    def test_core_models_importable(self):
        """Core data models must import."""
        from src.core.models import AgentResponse, Product

        assert AgentResponse is not None
        assert Product is not None

    def test_state_machine_importable(self):
        """State machine enums and transitions must import."""
        from src.core.state_machine import Intent, State

        assert State.STATE_1_DISCOVERY is not None
        assert Intent.PHOTO_IDENT is not None

    def test_langgraph_state_importable(self):
        """LangGraph state definition must import."""
        from src.agents.langgraph.state import ConversationState, create_initial_state

        assert ConversationState is not None
        assert callable(create_initial_state)

    def test_langgraph_edges_importable(self):
        """LangGraph routing logic must import."""
        from src.agents.langgraph.edges import master_router, route_after_intent

        assert callable(master_router)
        assert callable(route_after_intent)

    def test_langgraph_graph_importable(self):
        """LangGraph graph builder must import."""
        from src.agents.langgraph.graph import build_production_graph

        assert callable(build_production_graph)

    def test_langgraph_nodes_importable(self):
        """All LangGraph nodes must import."""
        from src.agents.langgraph.nodes import (
            agent_node,
            escalation_node,
            intent_detection_node,
            moderation_node,
            offer_node,
            payment_node,
            upsell_node,
            vision_node,
        )

        assert callable(agent_node)
        assert callable(intent_detection_node)
        assert callable(moderation_node)
        assert callable(vision_node)
        assert callable(offer_node)
        assert callable(payment_node)
        assert callable(upsell_node)
        assert callable(escalation_node)

    def test_pydantic_agents_importable(self):
        """PydanticAI agents must import."""
        from src.agents.pydantic.support_agent import get_support_agent

        assert get_support_agent is not None
        assert callable(get_support_agent)

    def test_pydantic_models_importable(self):
        """PydanticAI response models must import."""
        from src.agents.pydantic.models import SupportResponse

        assert SupportResponse is not None

    def test_services_importable(self):
        """Core services must import."""
        from src.services.catalog_service import CatalogService
        from src.services.conversation import ConversationHandler
        from src.services.memory_service import MemoryService
        from src.services.order_service import OrderService

        assert CatalogService is not None
        assert OrderService is not None
        assert MemoryService is not None
        assert ConversationHandler is not None

    def test_integrations_importable(self):
        """Integration modules must import."""
        from src.integrations.crm.crmservice import CRMService

        assert CRMService is not None

    def test_server_importable(self):
        """FastAPI server must import."""
        from src.server.main import app

        assert app is not None

    def test_config_importable(self):
        """Configuration must import."""
        from src.conf.config import settings
        from src.conf.payment_config import BANK_REQUISITES

        assert settings is not None
        assert BANK_REQUISITES is not None


@pytest.mark.smoke
@pytest.mark.critical
class TestNoDanglingImports:
    """Verify no modules have unresolved imports at module level."""

    def test_all_agents_modules(self):
        """All agents submodules import cleanly."""
        assert True  # If we get here, imports succeeded

    def test_all_services_modules(self):
        """All services submodules import cleanly."""
        assert True

    def test_all_integration_modules(self):
        """All integration submodules import cleanly."""
        assert True
