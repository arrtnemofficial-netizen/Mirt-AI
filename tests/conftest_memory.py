"""
Test Fixtures for Memory System.
=================================
Shared fixtures for memory tests.

Import in conftest.py:
    from tests.conftest_memory import *
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

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
# USER PROFILE FIXTURES
# =============================================================================


@pytest.fixture
def empty_profile():
    """Empty user profile."""
    return UserProfile(user_id="test_user")


@pytest.fixture
def full_profile():
    """Fully populated user profile."""
    return UserProfile(
        user_id="full_user",
        child_profile=ChildProfile(
            name="Марія",
            age=7,
            height_cm=128,
            gender="дівчинка",
            body_type="стандартна",
            height_history=[
                {"date": "2024-01", "height": 122},
                {"date": "2024-06", "height": 128},
            ],
        ),
        style_preferences=StylePreferences(
            favorite_models=["Лагуна", "Ритм"],
            preferred_styles=["спортивний", "святковий"],
            favorite_colors=["рожевий", "блакитний"],
            avoided_colors=["чорний"],
            fabric_preferences=["бавовна"],
        ),
        logistics=LogisticsInfo(
            city="Харків",
            delivery_type="nova_poshta",
            favorite_branch="Відділення №52",
        ),
        commerce=CommerceInfo(
            avg_check=1850.0,
            order_frequency="monthly",
            discount_sensitive=True,
            payment_preference="card_online",
            total_orders=5,
        ),
        completeness_score=0.85,
    )


@pytest.fixture
def kyiv_profile():
    """Profile with Kyiv logistics."""
    return UserProfile(
        user_id="kyiv_user",
        logistics=LogisticsInfo(city="Київ"),
    )


# =============================================================================
# FACT FIXTURES
# =============================================================================


@pytest.fixture
def high_importance_fact():
    """Fact with high importance (passes gating)."""
    return NewFact(
        content="Зріст дитини 128 см",
        fact_type="child_info",
        category="child",
        importance=0.9,
        surprise=0.8,
    )


@pytest.fixture
def low_importance_fact():
    """Fact with low importance (fails gating)."""
    return NewFact(
        content="Дякую",
        fact_type="feedback",
        category="general",
        importance=0.3,
        surprise=0.2,
    )


@pytest.fixture
def boundary_importance_fact():
    """Fact at gating boundary (importance=0.6, surprise=0.4)."""
    return NewFact(
        content="Улюблений колір рожевий",
        fact_type="preference",
        category="style",
        importance=0.6,
        surprise=0.4,
    )


@pytest.fixture
def stored_fact():
    """Fact as stored in database."""
    return Fact(
        id=uuid4(),
        user_id="test_user",
        session_id="session_123",
        content="Улюблений колір рожевий",
        fact_type="preference",
        category="style",
        importance=0.8,
        surprise=0.6,
        confidence=0.9,
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def expired_fact():
    """Fact that should be expired."""
    return Fact(
        id=uuid4(),
        user_id="test_user",
        content="Тимчасова інформація",
        fact_type="behavior",
        category="general",
        importance=0.5,
        surprise=0.3,
        ttl_days=1,
        is_active=True,
    )


@pytest.fixture
def multiple_facts():
    """List of multiple facts."""
    return [
        Fact(
            id=uuid4(),
            user_id="test_user",
            content=f"Fact {i}",
            fact_type="preference",
            category="style",
            importance=0.8 - (i * 0.1),
            surprise=0.6,
        )
        for i in range(5)
    ]


# =============================================================================
# MEMORY DECISION FIXTURES
# =============================================================================


@pytest.fixture
def ignore_decision():
    """Decision to ignore messages."""
    return MemoryDecision(
        ignore_messages=True,
        reasoning="No new information in messages",
    )


@pytest.fixture
def store_decision(high_importance_fact):
    """Decision to store new facts."""
    return MemoryDecision(
        new_facts=[high_importance_fact],
        profile_updates={"child_profile": {"height_cm": 128}},
        reasoning="Extracted child height",
    )


@pytest.fixture
def update_decision(stored_fact):
    """Decision to update existing fact."""
    return MemoryDecision(
        updates=[
            UpdateFact(
                fact_id=stored_fact.id,
                new_content="Новий зріст 135 см",
                importance=0.95,
                surprise=0.9,
            ),
        ],
        reasoning="Child height changed",
    )


# =============================================================================
# MEMORY CONTEXT FIXTURES
# =============================================================================


@pytest.fixture
def empty_context():
    """Empty memory context."""
    return MemoryContext()


@pytest.fixture
def full_context(full_profile, multiple_facts):
    """Full memory context with profile and facts."""
    return MemoryContext(
        profile=full_profile,
        facts=multiple_facts,
        summary=MemorySummary(
            summary_type="user",
            summary_text="Постійний клієнт з Харкова, донька 7 років",
            key_facts=["зріст 128", "любить рожевий"],
            facts_count=10,
        ),
    )


# =============================================================================
# STATE FIXTURES
# =============================================================================


@pytest.fixture
def base_state():
    """Base LangGraph state."""
    return {
        "session_id": "test_session",
        "trace_id": "test_trace",
        "metadata": {
            "user_id": "test_user",
            "channel": "instagram",
        },
        "messages": [],
        "current_state": "STATE_0_INIT",
        "dialog_phase": "INIT",
        "step_number": 0,
    }


@pytest.fixture
def state_with_messages(base_state):
    """State with user messages."""
    base_state["messages"] = [
        {"role": "user", "content": "Доброго дня! Шукаю костюм для доньки 7 років, зріст 128 см"},
        {"role": "assistant", "content": "Доброго дня! Я підберу варіанти."},
        {"role": "user", "content": "Ми з Харкова"},
    ]
    return base_state


@pytest.fixture
def state_offer_phase(base_state):
    """State in OFFER_MADE phase."""
    base_state["dialog_phase"] = "OFFER_MADE"
    base_state["current_state"] = "STATE_4_OFFER"
    return base_state


@pytest.fixture
def state_with_memory(base_state, full_profile, multiple_facts):
    """State with memory context populated."""
    base_state["memory_profile"] = full_profile
    base_state["memory_facts"] = multiple_facts
    base_state["memory_context_prompt"] = "### ЩО МИ ЗНАЄМО ПРО КЛІЄНТА:\n- Дитина: 7 років, 128 см"
    return base_state


# =============================================================================
# MOCK FIXTURES
# =============================================================================


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    mock = MagicMock()
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
    mock.execute.return_value = MagicMock(data=[])
    return mock


@pytest.fixture
def mock_memory_service(mock_supabase):
    """Mock MemoryService."""
    from src.services.memory_service import MemoryService

    service = MemoryService(client=mock_supabase)
    return service


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def make_fact(
    content: str,
    importance: float = 0.8,
    surprise: float = 0.6,
    fact_type: str = "preference",
    category: str = "general",
) -> NewFact:
    """Helper to create NewFact."""
    return NewFact(
        content=content,
        fact_type=fact_type,
        category=category,
        importance=importance,
        surprise=surprise,
    )


def make_profile(
    user_id: str,
    height_cm: int | None = None,
    age: int | None = None,
    city: str | None = None,
) -> UserProfile:
    """Helper to create UserProfile."""
    return UserProfile(
        user_id=user_id,
        child_profile=ChildProfile(height_cm=height_cm, age=age),
        logistics=LogisticsInfo(city=city),
    )
