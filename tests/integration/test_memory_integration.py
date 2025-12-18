"""
Integration Tests for Memory System.
=====================================
Tests for memory nodes, graph integration, and production safety.

Run: pytest tests/integration/test_memory_integration.py -v

CRITICAL: These tests ensure memory system doesn't break production!
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC
from uuid import uuid4

from src.agents.pydantic.memory_models import (
    ChildProfile,
    Fact,
    LogisticsInfo,
    MemoryContext,
    MemoryDecision,
    MemorySummary,
    NewFact,
    UserProfile,
)
from src.agents.pydantic.memory_agent import (
    analyze_for_memory,
    extract_quick_facts,
    MemoryDeps,
)


# =============================================================================
# TEST 1-15: Quick Facts Extraction (No LLM)
# =============================================================================

class TestQuickFactsExtraction:
    """Tests for regex-based quick facts extraction."""
    
    def test_01_extract_height_cm(self):
        """Test extracting height in cm."""
        facts = extract_quick_facts("доньці 128 см")
        assert len(facts) >= 1
        height_fact = next((f for f in facts if f["field"] == "height_cm"), None)
        assert height_fact is not None
        assert height_fact["extracted_value"] == 128
    
    def test_02_extract_height_with_word(self):
        """Test extracting height with 'зріст' word."""
        facts = extract_quick_facts("зріст 135")
        height_fact = next((f for f in facts if f["field"] == "height_cm"), None)
        assert height_fact is not None
        assert height_fact["extracted_value"] == 135
    
    def test_03_extract_age(self):
        """Test extracting age."""
        facts = extract_quick_facts("доньці 7 років")
        age_fact = next((f for f in facts if f["field"] == "age"), None)
        assert age_fact is not None
        assert age_fact["extracted_value"] == 7
    
    def test_04_extract_gender_girl(self):
        """Test extracting gender - girl."""
        facts = extract_quick_facts("для дівчинки")
        gender_fact = next((f for f in facts if f["field"] == "gender"), None)
        assert gender_fact is not None
        assert gender_fact["extracted_value"] == "дівчинка"
    
    def test_05_extract_gender_boy(self):
        """Test extracting gender - boy."""
        facts = extract_quick_facts("синові треба")
        gender_fact = next((f for f in facts if f["field"] == "gender"), None)
        assert gender_fact is not None
        assert gender_fact["extracted_value"] == "хлопчик"
    
    def test_06_extract_city_kyiv(self):
        """Test extracting city - Київ."""
        facts = extract_quick_facts("я з києва")
        city_fact = next((f for f in facts if f["field"] == "city"), None)
        assert city_fact is not None
        assert city_fact["extracted_value"] == "Київ"
    
    def test_07_extract_city_kharkiv(self):
        """Test extracting city - Харків."""
        facts = extract_quick_facts("живу в харкові")
        city_fact = next((f for f in facts if f["field"] == "city"), None)
        assert city_fact is not None
        assert city_fact["extracted_value"] == "Харків"
    
    def test_08_extract_city_odesa(self):
        """Test extracting city - Одеса."""
        facts = extract_quick_facts("доставка в одесу")
        city_fact = next((f for f in facts if f["field"] == "city"), None)
        assert city_fact is not None
        assert city_fact["extracted_value"] == "Одеса"
    
    def test_09_extract_multiple_facts(self):
        """Test extracting multiple facts from one message."""
        facts = extract_quick_facts("доньці 7 років, зріст 128 см, живемо в києві")
        assert len(facts) >= 3
        
        fields = [f["field"] for f in facts]
        assert "age" in fields
        assert "height_cm" in fields
        assert "city" in fields
    
    def test_10_no_facts_in_greeting(self):
        """Test no facts extracted from greeting."""
        facts = extract_quick_facts("Добрий день!")
        # Should have no child/logistics facts
        child_facts = [f for f in facts if f["field"] in ["height_cm", "age", "gender"]]
        assert len(child_facts) == 0
    
    def test_11_no_facts_in_thanks(self):
        """Test no facts extracted from thanks."""
        facts = extract_quick_facts("Дякую за допомогу!")
        assert len(facts) == 0
    
    def test_12_height_validation_range(self):
        """Test height only extracted in valid range (70-180)."""
        # Invalid height
        facts = extract_quick_facts("артикул 12345 см")
        height_fact = next((f for f in facts if f["field"] == "height_cm"), None)
        # Should not extract 12345 as height (out of range)
        if height_fact:
            assert 70 <= height_fact["extracted_value"] <= 180
    
    def test_13_age_validation_range(self):
        """Test age only extracted in valid range (0-18)."""
        facts = extract_quick_facts("доньці 5 років")
        age_fact = next((f for f in facts if f["field"] == "age"), None)
        assert age_fact is not None
        assert 0 <= age_fact["extracted_value"] <= 18
    
    def test_14_extract_from_ukrainian_text(self):
        """Test extraction from full Ukrainian text."""
        text = "Доброго дня! Шукаю костюм для дівчинки 10 років, зріст близько 140 см. Ми з Дніпра."
        facts = extract_quick_facts(text)
        
        assert len(facts) >= 2  # At least age/height or city
    
    def test_15_case_insensitive(self):
        """Test extraction is case insensitive."""
        facts = extract_quick_facts("ЗРІСТ 130 СМ")
        height_fact = next((f for f in facts if f["field"] == "height_cm"), None)
        assert height_fact is not None


# =============================================================================
# TEST 16-30: Memory Context Node
# =============================================================================

class TestMemoryContextNode:
    """Tests for memory_context_node."""
    
    @pytest.mark.asyncio
    async def test_16_context_node_no_user_id(self):
        """Test context node skips when no user_id."""
        from src.agents.langgraph.nodes.memory import memory_context_node
        
        state = {"session_id": "test", "metadata": {}}
        result = await memory_context_node(state)
        
        # Should just increment step, no memory
        assert "step_number" in result
        assert result.get("memory_profile") is None
    
    @pytest.mark.asyncio
    async def test_17_context_node_with_user_id(self):
        """Test context node loads memory for user."""
        from src.agents.langgraph.nodes.memory import memory_context_node
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.load_memory_context = AsyncMock(return_value=MemoryContext())
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
            }
            result = await memory_context_node(state)
            
            mock_service.load_memory_context.assert_called_once_with("user_123")
    
    @pytest.mark.asyncio
    async def test_18_context_node_service_disabled(self):
        """Test context node handles disabled service."""
        from src.agents.langgraph.nodes.memory import memory_context_node
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = False
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
            }
            result = await memory_context_node(state)
            
            assert "step_number" in result
    
    @pytest.mark.asyncio
    async def test_19_context_node_error_handling(self):
        """Test context node handles errors gracefully."""
        from src.agents.langgraph.nodes.memory import memory_context_node
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.load_memory_context = AsyncMock(side_effect=Exception("DB error"))
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
            }
            
            # Should NOT raise, should return gracefully
            result = await memory_context_node(state)
            assert "step_number" in result
    
    @pytest.mark.asyncio
    async def test_20_context_node_returns_profile(self):
        """Test context node returns profile in state."""
        from src.agents.langgraph.nodes.memory import memory_context_node
        
        profile = UserProfile(
            user_id="user_123",
            child_profile=ChildProfile(height_cm=128),
        )
        context = MemoryContext(profile=profile)
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.load_memory_context = AsyncMock(return_value=context)
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
            }
            result = await memory_context_node(state)
            
            assert result.get("memory_profile") is not None


# =============================================================================
# TEST 21-35: Memory Update Node
# =============================================================================

class TestMemoryUpdateNode:
    """Tests for memory_update_node."""
    
    @pytest.mark.asyncio
    async def test_21_update_node_no_user_id(self):
        """Test update node skips when no user_id."""
        from src.agents.langgraph.nodes.memory import memory_update_node
        
        state = {"session_id": "test", "metadata": {}, "dialog_phase": "OFFER_MADE"}
        result = await memory_update_node(state)
        
        assert "step_number" in result
    
    @pytest.mark.asyncio
    async def test_22_update_node_wrong_phase(self):
        """Test update node skips for non-trigger phase."""
        from src.agents.langgraph.nodes.memory import memory_update_node
        
        state = {
            "session_id": "test",
            "metadata": {"user_id": "user_123"},
            "dialog_phase": "DISCOVERY",  # Not a trigger phase
            "current_state": "STATE_1_DISCOVERY",
        }
        result = await memory_update_node(state)
        
        # Should just return step_number
        assert "step_number" in result
    
    @pytest.mark.asyncio
    async def test_23_update_node_trigger_phase_offer(self):
        """Test update node triggers for OFFER_MADE phase."""
        from src.agents.langgraph.nodes.memory import memory_update_node, MEMORY_TRIGGER_PHASES
        
        assert "OFFER_MADE" in MEMORY_TRIGGER_PHASES
    
    @pytest.mark.asyncio
    async def test_24_update_node_trigger_phase_completed(self):
        """Test update node triggers for COMPLETED phase."""
        from src.agents.langgraph.nodes.memory import MEMORY_TRIGGER_PHASES
        
        assert "COMPLETED" in MEMORY_TRIGGER_PHASES
    
    @pytest.mark.asyncio
    async def test_25_update_node_trigger_phase_complaint(self):
        """Test update node triggers for COMPLAINT phase."""
        from src.agents.langgraph.nodes.memory import MEMORY_TRIGGER_PHASES
        
        assert "COMPLAINT" in MEMORY_TRIGGER_PHASES
    
    @pytest.mark.asyncio
    async def test_26_update_node_trigger_state(self):
        """Test update node triggers for STATE_4_OFFER."""
        from src.agents.langgraph.nodes.memory import MEMORY_TRIGGER_STATES
        
        assert "STATE_4_OFFER" in MEMORY_TRIGGER_STATES
    
    @pytest.mark.asyncio
    async def test_27_update_node_error_handling(self):
        """Test update node handles errors gracefully."""
        from src.agents.langgraph.nodes.memory import memory_update_node
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.store_fact = AsyncMock(side_effect=Exception("DB error"))
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
                "dialog_phase": "OFFER_MADE",
                "current_state": "STATE_4_OFFER",
                "messages": [{"role": "user", "content": "зріст 128 см"}],
            }
            
            # Should NOT raise
            result = await memory_update_node(state)
            assert "step_number" in result
    
    @pytest.mark.asyncio
    async def test_28_update_node_extracts_quick_facts(self):
        """Test update node extracts quick facts from messages."""
        from src.agents.langgraph.nodes.memory import memory_update_node
        
        with patch('src.agents.langgraph.nodes.memory.MemoryService') as MockService:
            mock_service = MockService.return_value
            mock_service.enabled = True
            mock_service.store_fact = AsyncMock(return_value=MagicMock())
            mock_service.update_profile = AsyncMock()
            
            state = {
                "session_id": "test",
                "metadata": {"user_id": "user_123"},
                "dialog_phase": "OFFER_MADE",
                "current_state": "STATE_4_OFFER",
                "messages": [{"role": "user", "content": "доньці 7 років, зріст 128 см"}],
            }
            
            await memory_update_node(state)
            
            # Should call store_fact for extracted facts
            assert mock_service.store_fact.called


# =============================================================================
# TEST 29-40: Should Load/Update Memory Helpers
# =============================================================================

class TestMemoryHelpers:
    """Tests for should_load_memory and should_update_memory."""
    
    def test_29_should_load_no_user_id(self):
        """Test should_load_memory returns False without user_id."""
        from src.agents.langgraph.nodes.memory import should_load_memory
        
        state = {"metadata": {}}
        assert should_load_memory(state) is False
    
    def test_30_should_load_with_user_id(self):
        """Test should_load_memory returns True with user_id."""
        from src.agents.langgraph.nodes.memory import should_load_memory
        
        state = {"metadata": {"user_id": "user_123"}, "dialog_phase": "DISCOVERY"}
        assert should_load_memory(state) is True
    
    def test_31_should_load_complaint_phase(self):
        """Test should_load_memory returns False for COMPLAINT."""
        from src.agents.langgraph.nodes.memory import should_load_memory
        
        state = {"metadata": {"user_id": "user_123"}, "dialog_phase": "COMPLAINT"}
        assert should_load_memory(state) is False
    
    def test_32_should_update_no_user_id(self):
        """Test should_update_memory returns False without user_id."""
        from src.agents.langgraph.nodes.memory import should_update_memory
        
        state = {"metadata": {}, "dialog_phase": "OFFER_MADE"}
        assert should_update_memory(state) is False
    
    def test_33_should_update_trigger_phase(self):
        """Test should_update_memory returns True for trigger phase."""
        from src.agents.langgraph.nodes.memory import should_update_memory
        
        state = {"metadata": {"user_id": "user_123"}, "dialog_phase": "OFFER_MADE"}
        assert should_update_memory(state) is True
    
    def test_34_should_update_trigger_state(self):
        """Test should_update_memory returns True for trigger state."""
        from src.agents.langgraph.nodes.memory import should_update_memory
        
        state = {
            "metadata": {"user_id": "user_123"},
            "dialog_phase": "INIT",
            "current_state": "STATE_4_OFFER",
        }
        assert should_update_memory(state) is True
    
    def test_35_should_update_trigger_states(self):
        """Test should_update_memory returns True for trigger states (including early states)."""
        from src.agents.langgraph.nodes.memory import should_update_memory
        
        # STATE_1_DISCOVERY now triggers memory update (fixed to capture facts early)
        state = {
            "metadata": {"user_id": "user_123"},
            "dialog_phase": "DISCOVERY",
            "current_state": "STATE_1_DISCOVERY",
        }
        assert should_update_memory(state) is True
        
        # STATE_9_OUT_OF_DOMAIN should NOT trigger memory update
        state_out_of_domain = {
            "metadata": {"user_id": "user_123"},
            "dialog_phase": "OUT_OF_DOMAIN",
            "current_state": "STATE_9_OUT_OF_DOMAIN",
        }
        assert should_update_memory(state_out_of_domain) is False


# =============================================================================
# TEST 36-50: Production Safety Tests
# =============================================================================

class TestProductionSafety:
    """CRITICAL: Tests to ensure memory doesn't break production."""
    
    def test_36_gating_prevents_spam(self):
        """Test gating prevents storing low-quality facts."""
        from src.services.memory_service import MIN_IMPORTANCE_TO_STORE, MIN_SURPRISE_TO_STORE
        
        # Spam-like messages should have low importance/surprise
        # and should be rejected by gating
        assert MIN_IMPORTANCE_TO_STORE >= 0.5  # At least 50% importance
        assert MIN_SURPRISE_TO_STORE >= 0.3    # At least 30% surprise
    
    def test_37_memory_context_empty_is_safe(self):
        """Test empty MemoryContext doesn't break prompts."""
        ctx = MemoryContext()
        prompt = ctx.to_prompt_block()
        
        # Empty context should return empty string, not None or error
        assert prompt == ""
        assert isinstance(prompt, str)
    
    def test_38_user_profile_serializable(self):
        """Test UserProfile is JSON serializable."""
        import json
        
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(height_cm=128),
        )
        
        # Should not raise
        data = profile.model_dump()
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0
    
    def test_39_fact_serializable(self):
        """Test Fact is JSON serializable."""
        import json
        
        fact = Fact(
            id=uuid4(),
            user_id="test",
            content="test",
            fact_type="preference",
            category="general",
        )
        
        data = fact.model_dump()
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0
    
    def test_40_memory_decision_serializable(self):
        """Test MemoryDecision is JSON serializable."""
        import json
        
        decision = MemoryDecision(
            new_facts=[
                NewFact(
                    content="test",
                    fact_type="preference",
                    category="general",
                    importance=0.8,
                    surprise=0.6,
                ),
            ],
            ignore_messages=False,
        )
        
        data = decision.model_dump()
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0
    
    @pytest.mark.asyncio
    async def test_41_memory_node_doesnt_block_graph(self):
        """Test memory nodes don't block graph execution."""
        from src.agents.langgraph.nodes.memory import memory_context_node, memory_update_node
        
        # Both should return in reasonable time even with errors
        state = {"session_id": "test", "metadata": {}, "step_number": 0}
        
        result1 = await memory_context_node(state)
        result2 = await memory_update_node(state)
        
        assert "step_number" in result1
        assert "step_number" in result2
    
    def test_42_memory_context_prompt_max_length(self):
        """Test memory context prompt doesn't exceed reasonable length."""
        # Create context with many facts
        facts = [
            Fact(
                user_id="test",
                content=f"Fact number {i} " * 10,  # Long content
                fact_type="preference",
                category="general",
            )
            for i in range(20)
        ]
        
        ctx = MemoryContext(facts=facts)
        prompt = ctx.to_prompt_block()
        
        # Should be limited (max 10 facts in prompt)
        assert prompt.count("Fact number") <= 10
    
    def test_43_quick_facts_no_false_positives(self):
        """Test quick facts extraction doesn't have false positives."""
        # These should NOT extract facts
        test_cases = [
            "Добрий день",
            "Дякую",
            "Скільки коштує?",
            "Покажіть каталог",
            "Гарний день",
        ]
        
        for text in test_cases:
            facts = extract_quick_facts(text)
            child_facts = [f for f in facts if f["field"] in ["height_cm", "age"]]
            assert len(child_facts) == 0, f"False positive in: {text}"
    
    def test_44_importance_rounding(self):
        """Test importance values are properly rounded."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.777777,
            surprise=0.333333,
        )
        
        # Should be rounded to 2 decimal places
        assert fact.importance == 0.78
        assert fact.surprise == 0.33
    
    def test_45_memory_context_with_null_fields(self):
        """Test MemoryContext handles None fields gracefully."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(),  # All None
            logistics=LogisticsInfo(),     # All None
        )
        
        ctx = MemoryContext(profile=profile)
        prompt = ctx.to_prompt_block()
        
        # Should not crash, should return empty or minimal
        assert isinstance(prompt, str)
    
    def test_46_fact_types_complete(self):
        """Test all fact types are defined."""
        from src.agents.pydantic.memory_models import FactType
        
        expected_types = ["preference", "constraint", "logistics", "behavior", "feedback", "child_info"]
        # FactType is a Literal, check by trying to create facts
        for ft in expected_types:
            fact = NewFact(
                content="test",
                fact_type=ft,
                category="general",
                importance=0.5,
                surprise=0.5,
            )
            assert fact.fact_type == ft
    
    def test_47_category_types_complete(self):
        """Test all category types are defined."""
        expected_categories = ["child", "style", "delivery", "payment", "product", "complaint", "general"]
        
        for cat in expected_categories:
            fact = NewFact(
                content="test",
                fact_type="preference",
                category=cat,
                importance=0.5,
                surprise=0.5,
            )
            assert fact.category == cat
    
    @pytest.mark.asyncio
    async def test_48_disabled_service_returns_empty(self):
        """Test disabled service returns empty results, not errors."""
        with patch('src.services.memory_service.get_supabase_client', return_value=None):
            from src.services.memory_service import MemoryService
            
            service = MemoryService()
            
            profile = await service.get_profile("test")
            facts = await service.get_facts("test")
            
            assert profile is None
            assert facts == []
    
    def test_49_memory_deps_dataclass(self):
        """Test MemoryDeps is properly defined."""
        deps = MemoryDeps(
            user_id="test",
            session_id="session_123",
        )
        
        assert deps.user_id == "test"
        assert deps.session_id == "session_123"
        assert deps.profile is None
        assert deps.existing_facts == []
    
    def test_50_graph_routes_include_memory(self):
        """Test graph routes include memory_context."""
        from src.agents.langgraph.edges import get_moderation_routes
        
        routes = get_moderation_routes()
        
        # Moderation should route to memory_context (not directly to intent)
        assert routes["intent"] == "memory_context"
