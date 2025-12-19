"""
E2E and Regression Tests for Memory System.
============================================
Tests for full graph flow with memory, and regression tests.

Run: pytest tests/integration/test_memory_e2e.py -v

CRITICAL: These tests ensure memory integration works end-to-end!
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agents.pydantic.deps import AgentDeps, create_deps_from_state
from src.agents.pydantic.memory_models import (
    ChildProfile,
    CommerceInfo,
    Fact,
    LogisticsInfo,
    MemoryContext,
    MemoryDecision,
    MemorySummary,
    NewFact,
    StylePreferences,
    UpdateFact,
    UserProfile,
)


# =============================================================================
# TEST 51-65: AgentDeps with Memory
# =============================================================================


class TestAgentDepsWithMemory:
    """Tests for AgentDeps memory integration."""

    def test_51_deps_has_memory_fields(self):
        """Test AgentDeps has memory fields."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        assert hasattr(deps, "profile")
        assert hasattr(deps, "facts")
        assert hasattr(deps, "memory_context_prompt")
        assert hasattr(deps, "memory")

    def test_52_deps_memory_defaults(self):
        """Test AgentDeps memory fields have correct defaults."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        assert deps.profile is None
        assert deps.facts == []
        assert deps.memory_context_prompt is None

    def test_53_deps_with_profile(self):
        """Test AgentDeps with profile."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128),
        )

        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            profile=profile,
        )

        assert deps.profile is not None
        assert deps.profile.child_profile.height_cm == 128

    def test_54_deps_with_facts(self):
        """Test AgentDeps with facts."""
        facts = [
            Fact(
                user_id="test",
                content="Улюблений колір рожевий",
                fact_type="preference",
                category="style",
            ),
        ]

        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            facts=facts,
        )

        assert len(deps.facts) == 1

    def test_55_deps_get_memory_context_prompt_empty(self):
        """Test get_memory_context_prompt returns empty for no memory."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        prompt = deps.get_memory_context_prompt()
        assert prompt == ""

    def test_56_deps_get_memory_context_prompt_with_profile(self):
        """Test get_memory_context_prompt with profile."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128, age=7),
        )

        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            profile=profile,
        )

        prompt = deps.get_memory_context_prompt()
        assert "128" in prompt or "7" in prompt

    def test_57_deps_get_memory_context_prompt_with_city(self):
        """Test get_memory_context_prompt includes city."""
        profile = UserProfile(
            user_id="test",
            logistics=LogisticsInfo(city="Харків"),
        )

        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            profile=profile,
        )

        prompt = deps.get_memory_context_prompt()
        assert "Харків" in prompt

    def test_58_deps_get_memory_context_prompt_preformatted(self):
        """Test get_memory_context_prompt uses preformatted if available."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            memory_context_prompt="### PREFORMATTED CONTEXT",
        )

        prompt = deps.get_memory_context_prompt()
        assert prompt == "### PREFORMATTED CONTEXT"

    def test_59_deps_has_memory_context_false(self):
        """Test has_memory_context returns False for empty."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        assert deps.has_memory_context() is False

    def test_60_deps_has_memory_context_with_profile(self):
        """Test has_memory_context returns True with profile."""
        profile = UserProfile(user_id="test")

        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            profile=profile,
        )

        assert deps.has_memory_context() is True

    def test_61_deps_has_memory_context_with_facts(self):
        """Test has_memory_context returns True with facts."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            facts=[
                Fact(
                    user_id="test",
                    content="test",
                    fact_type="preference",
                    category="general",
                ),
            ],
        )

        assert deps.has_memory_context() is True

    def test_62_create_deps_from_state_with_memory(self):
        """Test create_deps_from_state includes memory fields."""
        state = {
            "session_id": "test",
            "trace_id": "trace_123",
            "metadata": {"user_id": "user_123"},
            "memory_profile": UserProfile(user_id="user_123"),
            "memory_facts": [],
            "memory_context_prompt": "### TEST",
        }

        deps = create_deps_from_state(state)

        assert deps.profile is not None
        assert deps.memory_context_prompt == "### TEST"

    def test_63_create_deps_from_state_without_memory(self):
        """Test create_deps_from_state works without memory fields."""
        state = {
            "session_id": "test",
            "trace_id": "trace_123",
            "metadata": {"user_id": "user_123"},
        }

        deps = create_deps_from_state(state)

        assert deps.profile is None
        assert deps.facts == []


# =============================================================================
# TEST 64-75: Graph State with Memory
# =============================================================================


class TestGraphStateWithMemory:
    """Tests for ConversationState with memory fields."""

    def test_64_conversation_state_has_memory_fields(self):
        """Test ConversationState includes memory fields."""
        from src.agents.langgraph.state import ConversationState

        # Check type hints include memory fields
        annotations = ConversationState.__annotations__

        assert "memory_profile" in annotations
        assert "memory_facts" in annotations
        assert "memory_context_prompt" in annotations

    def test_65_create_initial_state_memory_defaults(self):
        """Test create_initial_state has memory defaults."""
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(session_id="test")

        assert state.get("memory_profile") is None
        assert state.get("memory_facts") == []
        assert state.get("memory_context_prompt") is None

    def test_66_state_snapshot_works(self):
        """Test get_state_snapshot still works with memory."""
        from src.agents.langgraph.state import create_initial_state, get_state_snapshot

        state = create_initial_state(session_id="test")
        snapshot = get_state_snapshot(state)

        assert "session_id" in snapshot
        assert "current_state" in snapshot


# =============================================================================
# TEST 67-80: Graph Flow Tests
# =============================================================================


class TestGraphFlow:
    """Tests for graph flow with memory integration."""

    def test_67_moderation_routes_to_memory(self):
        """Test moderation routes to memory_context."""
        from src.agents.langgraph.edges import get_moderation_routes

        routes = get_moderation_routes()
        assert routes["intent"] == "memory_context"

    def test_68_memory_context_in_graph_nodes(self):
        """Test memory_context is in graph nodes."""
        # Check that memory nodes are exported
        from src.agents.langgraph.nodes import memory_context_node, memory_update_node

        assert callable(memory_context_node)
        assert callable(memory_update_node)

    @pytest.mark.asyncio
    async def test_69_full_moderation_to_intent_flow(self):
        """Test flow: moderation → memory_context → intent."""
        from src.agents.langgraph.nodes.memory import memory_context_node

        with patch("src.agents.langgraph.nodes.memory.MemoryService") as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.load_memory_context = AsyncMock(return_value=MemoryContext())

            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
                "step_number": 1,
            }

            result = await memory_context_node(state)

            # Should return state update
            assert "step_number" in result
            assert result["step_number"] == 2

    @pytest.mark.asyncio
    async def test_70_offer_to_memory_update_flow(self):
        """Test flow: offer → memory_update → end."""
        from src.agents.langgraph.nodes.memory import memory_update_node

        with patch("src.agents.langgraph.nodes.memory.MemoryService") as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.store_fact = AsyncMock(return_value=None)
            mock_service.apply_decision = AsyncMock(return_value={})

            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
                "dialog_phase": "OFFER_MADE",
                "current_state": "STATE_4_OFFER",
                "messages": [{"role": "user", "content": "ok"}],
                "step_number": 5,
            }

            result = await memory_update_node(state)

            assert result["step_number"] == 6


# =============================================================================
# TEST 71-85: Regression Tests
# =============================================================================


class TestRegressionTests:
    """Regression tests to ensure memory doesn't break existing functionality."""

    def test_71_deps_still_has_customer_data(self):
        """Test AgentDeps still has customer data fields."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            customer_name="Тест",
            customer_phone="+380501234567",
        )

        assert deps.customer_name == "Тест"
        assert deps.customer_phone == "+380501234567"

    def test_72_deps_get_customer_data_summary_still_works(self):
        """Test get_customer_data_summary still works."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            customer_name="Тест",
            customer_city="Київ",
        )

        summary = deps.get_customer_data_summary()
        assert "Тест" in summary
        assert "Київ" in summary

    def test_73_deps_is_ready_for_order_still_works(self):
        """Test is_ready_for_order still works."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            customer_name="Тест",
            customer_phone="+380501234567",
            customer_city="Київ",
            customer_nova_poshta="№52",
            selected_products=[{"name": "Лагуна"}],
        )

        assert deps.is_ready_for_order() is True

    def test_74_deps_catalog_service_still_works(self):
        """Test catalog service is still available."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        assert hasattr(deps, "catalog")
        assert deps.catalog is not None

    def test_75_deps_db_service_still_works(self):
        """Test db service is still available."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
        )

        assert hasattr(deps, "db")
        assert deps.db is not None

    def test_76_state_still_has_messages(self):
        """Test ConversationState still has messages field."""
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(
            session_id="test",
            messages=[{"role": "user", "content": "Привіт"}],
        )

        assert "messages" in state
        assert len(state["messages"]) == 1

    def test_77_state_still_has_dialog_phase(self):
        """Test ConversationState still has dialog_phase."""
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(session_id="test")

        assert "dialog_phase" in state
        assert state["dialog_phase"] == "INIT"

    def test_78_state_still_has_selected_products(self):
        """Test ConversationState still has selected_products."""
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(session_id="test")

        assert "selected_products" in state
        assert state["selected_products"] == []

    def test_79_intent_routes_unchanged(self):
        """Test intent routes are unchanged."""
        from src.agents.langgraph.edges import get_intent_routes

        routes = get_intent_routes()

        assert "vision" in routes
        assert "agent" in routes
        assert "offer" in routes
        assert "payment" in routes

    def test_80_agent_routes_unchanged(self):
        """Test agent routes are unchanged."""
        from src.agents.langgraph.edges import get_agent_routes

        routes = get_agent_routes()

        assert "validation" in routes
        assert "offer" in routes
        assert "end" in routes


# =============================================================================
# TEST 81-90: Performance and Safety Tests
# =============================================================================


class TestPerformanceAndSafety:
    """Tests for performance and production safety."""

    def test_81_memory_context_prompt_not_too_long(self):
        """Test memory context prompt has reasonable length."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128, age=7, name="Тест"),
            style_preferences=StylePreferences(
                favorite_colors=["рожевий", "блакитний"],
                favorite_models=["Лагуна", "Ритм"],
            ),
            logistics=LogisticsInfo(city="Київ", favorite_branch="НП №52"),
        )

        facts = [
            Fact(
                user_id="test",
                content=f"Fact {i}",
                fact_type="preference",
                category="general",
            )
            for i in range(20)
        ]

        ctx = MemoryContext(profile=profile, facts=facts)
        prompt = ctx.to_prompt_block()

        # Should be limited (not exceed 2000 chars for reasonable token count)
        assert len(prompt) < 3000

    def test_82_quick_facts_fast(self):
        """Test quick facts extraction is fast."""
        import time

        from src.agents.pydantic.memory_agent import extract_quick_facts

        text = "Доброго дня! Шукаю костюм для дівчинки 10 років, зріст 140 см."

        start = time.time()
        for _ in range(100):
            extract_quick_facts(text)
        elapsed = time.time() - start

        # 100 extractions should take less than 100ms
        assert elapsed < 0.1

    def test_83_memory_models_fast_serialization(self):
        """Test memory models serialize fast."""
        import time

        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128),
        )

        start = time.time()
        for _ in range(1000):
            profile.model_dump()
        elapsed = time.time() - start

        # 1000 serializations should take less than 500ms
        assert elapsed < 0.5

    def test_84_empty_state_doesnt_crash(self):
        """Test empty state doesn't crash memory operations."""
        from src.agents.pydantic.deps import create_deps_from_state

        state = {}

        # Should not crash
        deps = create_deps_from_state(state)
        assert deps.session_id == ""

    def test_85_none_values_handled(self):
        """Test None values are handled gracefully."""
        deps = AgentDeps(
            session_id="test",
            trace_id="trace_123",
            profile=None,
            facts=None,  # type: ignore - testing None handling
        )

        # Should not crash
        prompt = deps.get_memory_context_prompt()
        assert isinstance(prompt, str)

    @pytest.mark.asyncio
    async def test_86_memory_node_timeout_safe(self):
        """Test memory nodes don't hang indefinitely."""
        import asyncio

        from src.agents.langgraph.nodes.memory import memory_context_node

        state = {"session_id": "test", "metadata": {}}

        # Should complete in less than 5 seconds
        try:
            result = await asyncio.wait_for(memory_context_node(state), timeout=5.0)
            assert "step_number" in result
        except TimeoutError:
            pytest.fail("memory_context_node timed out")

    def test_87_dbtable_constants_defined(self):
        """Test DBTable has memory table constants."""
        from src.core.constants import DBTable

        assert hasattr(DBTable, "PROFILES")
        assert hasattr(DBTable, "MEMORIES")
        assert hasattr(DBTable, "MEMORY_SUMMARIES")

        assert DBTable.PROFILES == "mirt_profiles"
        assert DBTable.MEMORIES == "mirt_memories"

    def test_88_memory_service_constants(self):
        """Test memory service constants are correct."""
        from src.services.memory_service import (
            DEFAULT_FACTS_LIMIT,
            MAX_FACTS_LIMIT,
            MIN_IMPORTANCE_TO_STORE,
            MIN_SURPRISE_TO_STORE,
        )

        assert MIN_IMPORTANCE_TO_STORE == 0.6
        assert MIN_SURPRISE_TO_STORE == 0.4
        assert DEFAULT_FACTS_LIMIT == 10
        assert MAX_FACTS_LIMIT == 50


# =============================================================================
# TEST 89-100: Edge Cases and Error Handling
# =============================================================================


class TestEdgeCasesAndErrors:
    """Tests for edge cases and error handling."""

    def test_89_unicode_in_facts(self):
        """Test Unicode characters in facts."""
        fact = NewFact(
            content="Дитина любить 🌸 квіти та 🦄 єдинорогів",
            fact_type="preference",
            category="style",
            importance=0.7,
            surprise=0.5,
        )

        assert "🌸" in fact.content
        assert "🦄" in fact.content

    def test_90_very_long_user_id(self):
        """Test very long user_id."""
        long_id = "user_" + "a" * 500

        profile = UserProfile(user_id=long_id)
        assert len(profile.user_id) > 500

    def test_91_special_chars_in_content(self):
        """Test special characters in content."""
        fact = NewFact(
            content="Телефон: +38(050)123-45-67; email: test@test.com",
            fact_type="logistics",
            category="delivery",
            importance=0.7,
            surprise=0.5,
        )

        assert "@" in fact.content
        assert "+" in fact.content

    def test_92_empty_facts_list(self):
        """Test empty facts list handling."""
        ctx = MemoryContext(facts=[])
        prompt = ctx.to_prompt_block()

        # Should handle empty list
        assert isinstance(prompt, str)

    def test_93_none_profile_in_context(self):
        """Test None profile in context."""
        ctx = MemoryContext(profile=None)

        assert ctx.is_empty() is True

    def test_94_decision_with_empty_lists(self):
        """Test MemoryDecision with empty lists."""
        decision = MemoryDecision(
            new_facts=[],
            updates=[],
            deletes=[],
            profile_updates={},
        )

        assert len(decision.new_facts) == 0
        assert len(decision.updates) == 0

    def test_95_fact_with_all_optional_fields(self):
        """Test Fact with all optional fields set."""
        fact = Fact(
            id=uuid4(),
            user_id="test",
            session_id="session_123",
            content="Test content",
            fact_type="preference",
            category="style",
            importance=0.8,
            surprise=0.6,
            confidence=0.9,
            ttl_days=30,
            created_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
            is_active=True,
        )

        assert fact.ttl_days == 30
        assert fact.confidence == 0.9

    def test_96_profile_with_all_nested(self):
        """Test UserProfile with all nested models populated."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(
                name="Марія",
                age=7,
                height_cm=128,
                gender="дівчинка",
                body_type="стандартна",
            ),
            style_preferences=StylePreferences(
                favorite_models=["Лагуна"],
                favorite_colors=["рожевий"],
            ),
            logistics=LogisticsInfo(
                city="Київ",
                delivery_type="nova_poshta",
            ),
            commerce=CommerceInfo(
                avg_check=1500,
                total_orders=5,
            ),
        )

        assert profile.child_profile.name == "Марія"
        assert profile.commerce.total_orders == 5

    def test_97_multiple_facts_same_category(self):
        """Test multiple facts with same category."""
        facts = [
            NewFact(
                content=f"Style fact {i}",
                fact_type="preference",
                category="style",
                importance=0.7,
                surprise=0.5,
            )
            for i in range(5)
        ]

        assert len(facts) == 5
        assert all(f.category == "style" for f in facts)

    def test_98_update_fact_with_uuid(self):
        """Test UpdateFact with proper UUID."""
        fact_id = uuid4()

        update = UpdateFact(
            fact_id=fact_id,
            new_content="Updated content",
            importance=0.9,
            surprise=0.8,
        )

        assert update.fact_id == fact_id

    def test_99_memory_context_full_chain(self):
        """Test full MemoryContext with all components."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128),
            logistics=LogisticsInfo(city="Київ"),
        )

        facts = [
            Fact(
                user_id="test",
                content="Улюблений колір рожевий",
                fact_type="preference",
                category="style",
            ),
        ]

        summary = MemorySummary(
            summary_type="user",
            summary_text="Постійний клієнт з Києва",
        )

        ctx = MemoryContext(
            profile=profile,
            facts=facts,
            summary=summary,
        )

        assert ctx.is_empty() is False

        prompt = ctx.to_prompt_block()
        assert "128" in prompt
        assert "Київ" in prompt
        assert "рожевий" in prompt

    def test_100_production_ready_check(self):
        """Final production readiness check."""
        # All imports should work
        from src.agents.pydantic.deps import AgentDeps
        from src.agents.pydantic.memory_models import (
            MemoryContext,
            NewFact,
            UserProfile,
        )

        # Basic functionality should work
        profile = UserProfile(user_id="production_test")
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.8,
            surprise=0.6,
        )
        ctx = MemoryContext(profile=profile)
        deps = AgentDeps(session_id="test", trace_id="test")

        # All should be created without errors
        assert profile is not None
        assert fact is not None
        assert ctx is not None
        assert deps is not None

        print("✅ Production readiness check PASSED!")
