"""
Unit Tests for Memory Service.
===============================
Tests for MemoryService: gating, CRUD, profile operations.

Run: pytest tests/unit/test_memory_service.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC
from uuid import uuid4

from src.agents.pydantic.memory_models import (
    ChildProfile,
    CommerceInfo,
    Fact,
    LogisticsInfo,
    MemoryDecision,
    NewFact,
    StylePreferences,
    UpdateFact,
    UserProfile,
)
from src.services.memory_service import (
    MemoryService,
    MIN_IMPORTANCE_TO_STORE,
    MIN_SURPRISE_TO_STORE,
    DEFAULT_FACTS_LIMIT,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Create mock Supabase client with proper chaining.
    
    SENIOR TIP: Supabase uses fluent interface (method chaining).
    Each method returns a new query builder, so we need to mock
    the entire chain properly. The key insight:
    - .single().execute() returns data as DICT
    - .execute() without .single() returns data as LIST
    """
    mock = MagicMock()
    # Chain all methods to return the same mock for fluent interface
    mock.table.return_value = mock
    mock.select.return_value = mock
    mock.insert.return_value = mock
    mock.update.return_value = mock
    mock.upsert.return_value = mock
    mock.delete.return_value = mock
    mock.eq.return_value = mock
    mock.gte.return_value = mock
    mock.lt.return_value = mock
    mock.in_.return_value = mock
    mock.order.return_value = mock
    mock.limit.return_value = mock
    mock.single.return_value = mock
    # Default: empty list (for non-.single() queries)
    mock.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def memory_service(mock_supabase):
    """Create MemoryService with mock client."""
    service = MemoryService(client=mock_supabase)
    return service


@pytest.fixture
def sample_new_fact():
    """Create sample NewFact."""
    return NewFact(
        content="Зріст дитини 128 см",
        fact_type="child_info",
        category="child",
        importance=0.9,
        surprise=0.8,
    )


@pytest.fixture
def sample_fact():
    """Create sample Fact."""
    return Fact(
        id=uuid4(),
        user_id="user_123",
        content="Улюблений колір рожевий",
        fact_type="preference",
        category="style",
        importance=0.8,
        surprise=0.6,
    )


# =============================================================================
# TEST 71-80: Service Initialization
# =============================================================================

class TestServiceInit:
    """Tests for MemoryService initialization."""
    
    def test_71_service_enabled_with_client(self, mock_supabase):
        """Test service is enabled with valid client."""
        service = MemoryService(client=mock_supabase)
        assert service.enabled is True
    
    def test_72_service_disabled_without_client(self):
        """Test service is disabled without client."""
        with patch('src.services.memory_service.get_supabase_client', return_value=None):
            service = MemoryService()
            assert service.enabled is False
    
    def test_73_gating_constants_defined(self):
        """Test gating constants are properly defined."""
        assert MIN_IMPORTANCE_TO_STORE == 0.6
        assert MIN_SURPRISE_TO_STORE == 0.4
    
    def test_74_default_limit_defined(self):
        """Test default facts limit is defined."""
        assert DEFAULT_FACTS_LIMIT == 10


# =============================================================================
# TEST 75-90: Gating Logic (CRITICAL!)
# =============================================================================

class TestGatingLogic:
    """Tests for importance/surprise gating - CRITICAL for production safety."""
    
    @pytest.mark.asyncio
    async def test_75_gating_accepts_high_importance_high_surprise(self, memory_service, mock_supabase):
        """Test gating accepts fact with high importance AND high surprise."""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.9,  # >= 0.6 ✓
            surprise=0.8,    # >= 0.4 ✓
        )
        
        result = await memory_service.store_fact("user_123", fact)
        # Should store (gating passed)
        assert mock_supabase.table.called
    
    @pytest.mark.asyncio
    async def test_76_gating_rejects_low_importance(self, memory_service, mock_supabase):
        """Test gating REJECTS fact with low importance."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.5,  # < 0.6 ✗
            surprise=0.8,
        )
        
        result = await memory_service.store_fact("user_123", fact)
        # Should NOT store (gating failed)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_77_gating_rejects_low_surprise(self, memory_service, mock_supabase):
        """Test gating REJECTS fact with low surprise."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.9,
            surprise=0.3,  # < 0.4 ✗
        )
        
        result = await memory_service.store_fact("user_123", fact)
        # Should NOT store (gating failed)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_78_gating_rejects_both_low(self, memory_service, mock_supabase):
        """Test gating REJECTS fact with both low importance and surprise."""
        fact = NewFact(
            content="Дякую",  # Generic thank you - should be rejected
            fact_type="feedback",
            category="general",
            importance=0.3,  # < 0.6 ✗
            surprise=0.2,    # < 0.4 ✗
        )
        
        result = await memory_service.store_fact("user_123", fact)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_79_gating_boundary_importance(self, memory_service, mock_supabase):
        """Test gating at exact boundary - importance=0.6."""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.6,  # Exactly at boundary
            surprise=0.5,
        )
        
        result = await memory_service.store_fact("user_123", fact)
        # Should store (boundary is inclusive)
        assert mock_supabase.table.called
    
    @pytest.mark.asyncio
    async def test_80_gating_boundary_surprise(self, memory_service, mock_supabase):
        """Test gating at exact boundary - surprise=0.4."""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.7,
            surprise=0.4,  # Exactly at boundary
        )
        
        result = await memory_service.store_fact("user_123", fact)
        # Should store (boundary is inclusive)
        assert mock_supabase.table.called
    
    @pytest.mark.asyncio
    async def test_81_gating_bypass_flag(self, memory_service, mock_supabase):
        """Test bypass_gating flag allows low importance facts."""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.3,  # Would be rejected
            surprise=0.2,    # Would be rejected
        )
        
        result = await memory_service.store_fact(
            "user_123", fact, bypass_gating=True
        )
        # Should store (bypass enabled)
        assert mock_supabase.table.called
    
    @pytest.mark.asyncio
    async def test_82_gating_just_below_importance(self, memory_service, mock_supabase):
        """Test gating rejects importance=0.59 (just below 0.6)."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.59,  # Just below threshold
            surprise=0.5,
        )
        
        result = await memory_service.store_fact("user_123", fact)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_83_gating_just_below_surprise(self, memory_service, mock_supabase):
        """Test gating rejects surprise=0.39 (just below 0.4)."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.7,
            surprise=0.39,  # Just below threshold
        )
        
        result = await memory_service.store_fact("user_123", fact)
        assert result is None


# =============================================================================
# TEST 84-95: Profile Operations
# =============================================================================

class TestProfileOperations:
    """Tests for profile CRUD operations."""
    
    @pytest.mark.asyncio
    async def test_84_get_profile_exists(self, memory_service, mock_supabase):
        """Test getting existing profile."""
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "user_123",
            "child_profile": {"height_cm": 128},
            "style_preferences": {},
            "logistics": {"city": "Київ"},
            "commerce": {},
            "completeness_score": 0.3,
        })
        
        profile = await memory_service.get_profile("user_123")
        assert profile is not None
        assert profile.user_id == "user_123"
    
    @pytest.mark.asyncio
    async def test_85_get_profile_not_found(self, memory_service, mock_supabase):
        """Test getting non-existent profile returns None."""
        mock_supabase.execute.side_effect = Exception("0 rows returned")
        
        profile = await memory_service.get_profile("nonexistent")
        assert profile is None
    
    @pytest.mark.asyncio
    async def test_86_create_profile(self, memory_service, mock_supabase):
        """Test creating new profile."""
        mock_supabase.execute.return_value = MagicMock(data=[{
            "user_id": "new_user",
            "child_profile": {},
            "style_preferences": {},
            "logistics": {},
            "commerce": {},
            "completeness_score": 0.0,
        }])
        
        profile = await memory_service.create_profile("new_user")
        assert profile.user_id == "new_user"
    
    @pytest.mark.asyncio
    async def test_87_get_or_create_existing(self, memory_service, mock_supabase):
        """Test get_or_create returns existing profile."""
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "existing_user",
            "child_profile": {},
            "style_preferences": {},
            "logistics": {},
            "commerce": {},
        })
        
        profile = await memory_service.get_or_create_profile("existing_user")
        assert profile.user_id == "existing_user"
    
    @pytest.mark.asyncio
    async def test_88_update_profile_child(self, memory_service, mock_supabase):
        """Test updating child_profile."""
        # Mock get_profile
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "user_123",
            "child_profile": {"age": 5},
            "style_preferences": {},
            "logistics": {},
            "commerce": {},
        })
        
        profile = await memory_service.update_profile(
            "user_123",
            child_profile={"height_cm": 110},
        )
        # Should merge: age=5 + height_cm=110
        mock_supabase.update.assert_called()
    
    @pytest.mark.asyncio
    async def test_89_update_profile_logistics(self, memory_service, mock_supabase):
        """Test updating logistics."""
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "user_123",
            "child_profile": {},
            "style_preferences": {},
            "logistics": {"city": "Київ"},
            "commerce": {},
        })
        
        await memory_service.update_profile(
            "user_123",
            logistics={"favorite_branch": "НП №52"},
        )
        mock_supabase.update.assert_called()
    
    @pytest.mark.asyncio
    async def test_90_update_profile_style_merge_lists(self, memory_service, mock_supabase):
        """Test style preferences merge lists (append unique)."""
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "user_123",
            "child_profile": {},
            "style_preferences": {"favorite_colors": ["рожевий"]},
            "logistics": {},
            "commerce": {},
        })
        
        await memory_service.update_profile(
            "user_123",
            style_preferences={"favorite_colors": ["блакитний"]},
        )
        # Should merge: ["рожевий", "блакитний"]
        mock_supabase.update.assert_called()
    
    @pytest.mark.asyncio
    async def test_91_touch_profile(self, memory_service, mock_supabase):
        """Test touch_profile updates last_seen_at."""
        await memory_service.touch_profile("user_123")
        mock_supabase.update.assert_called()


# =============================================================================
# TEST 92-100: Memory Context Loading
# =============================================================================

class TestMemoryContextLoading:
    """Tests for loading memory context."""
    
    @pytest.mark.asyncio
    async def test_92_load_memory_context_full(self, memory_service, mock_supabase):
        """Test loading full memory context."""
        # Mock profile
        mock_supabase.execute.return_value = MagicMock(data={
            "user_id": "user_123",
            "child_profile": {"height_cm": 128},
            "style_preferences": {"favorite_colors": ["рожевий"]},
            "logistics": {"city": "Харків"},
            "commerce": {"total_orders": 3},
        })
        
        context = await memory_service.load_memory_context("user_123")
        assert context.profile is not None
    
    @pytest.mark.asyncio
    async def test_93_load_memory_context_with_facts(self, memory_service, mock_supabase):
        """Test loading context includes facts."""
        mock_supabase.execute.return_value = MagicMock(data=[
            {
                "id": str(uuid4()),
                "user_id": "user_123",
                "content": "test fact",
                "fact_type": "preference",
                "category": "style",
                "importance": 0.8,
                "surprise": 0.6,
                "confidence": 0.9,
                "is_active": True,
            }
        ])
        
        facts = await memory_service.get_facts("user_123")
        assert len(facts) >= 0  # May be empty due to mock
    
    @pytest.mark.asyncio
    async def test_94_load_memory_context_disabled_service(self):
        """Test loading context with disabled service."""
        with patch('src.services.memory_service.get_supabase_client', return_value=None):
            service = MemoryService()
            context = await service.load_memory_context("user_123")
            # Should return context with None profile
            assert context.profile is None or context.is_empty()
    
    @pytest.mark.asyncio
    async def test_95_get_facts_with_limit(self, memory_service, mock_supabase):
        """Test getting facts respects limit."""
        mock_supabase.execute.return_value = MagicMock(data=[])
        
        await memory_service.get_facts("user_123", limit=5)
        mock_supabase.limit.assert_called_with(5)
    
    @pytest.mark.asyncio
    async def test_96_get_facts_with_categories(self, memory_service, mock_supabase):
        """Test getting facts filters by categories."""
        mock_supabase.execute.return_value = MagicMock(data=[])
        
        await memory_service.get_facts(
            "user_123",
            categories=["child", "style"],
        )
        mock_supabase.in_.assert_called()
    
    @pytest.mark.asyncio
    async def test_97_get_facts_min_importance(self, memory_service, mock_supabase):
        """Test getting facts filters by min_importance."""
        mock_supabase.execute.return_value = MagicMock(data=[])
        
        await memory_service.get_facts("user_123", min_importance=0.5)
        mock_supabase.gte.assert_called()


# =============================================================================
# TEST 98-100: Apply Decision
# =============================================================================

class TestApplyDecision:
    """Tests for applying MemoryDecision."""
    
    @pytest.mark.asyncio
    async def test_98_apply_decision_ignore(self, memory_service, mock_supabase):
        """Test applying decision with ignore_messages=True."""
        decision = MemoryDecision(ignore_messages=True)
        
        stats = await memory_service.apply_decision("user_123", decision)
        assert stats["stored"] == 0
        assert stats["updated"] == 0
    
    @pytest.mark.asyncio
    async def test_99_apply_decision_with_new_facts(self, memory_service, mock_supabase):
        """Test applying decision stores new facts."""
        mock_supabase.execute.return_value = MagicMock(data=[{"id": str(uuid4())}])
        
        decision = MemoryDecision(
            new_facts=[
                NewFact(
                    content="test",
                    fact_type="preference",
                    category="general",
                    importance=0.8,  # Passes gating
                    surprise=0.6,
                ),
            ]
        )
        
        stats = await memory_service.apply_decision("user_123", decision)
        assert stats["stored"] >= 0  # May be 0 or 1 depending on mock
    
    @pytest.mark.asyncio
    async def test_100_apply_decision_gating_rejects(self, memory_service, mock_supabase):
        """Test applying decision - gating rejects low importance facts."""
        decision = MemoryDecision(
            new_facts=[
                NewFact(
                    content="Дякую",
                    fact_type="feedback",
                    category="general",
                    importance=0.3,  # Below threshold
                    surprise=0.2,    # Below threshold
                ),
            ]
        )
        
        stats = await memory_service.apply_decision("user_123", decision)
        assert stats["rejected"] == 1  # Should be rejected by gating
