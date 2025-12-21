"""
Unit Tests for Memory Models.
==============================
Tests for Pydantic models: UserProfile, Fact, MemoryDecision, etc.

Run: pytest tests/test_memory_models.py -v
"""

from uuid import uuid4

import pytest

from src.agents.pydantic.memory_models import (
    ChildProfile,
    CommerceInfo,
    DeleteFact,
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
# TEST 1-10: ChildProfile Model
# =============================================================================


class TestChildProfile:
    """Tests for ChildProfile model."""

    def test_01_child_profile_defaults(self):
        """Test ChildProfile with default values."""
        profile = ChildProfile()
        assert profile.name is None
        assert profile.age is None
        assert profile.height_cm is None
        assert profile.gender is None
        assert profile.body_type is None
        assert profile.height_history == []

    def test_02_child_profile_full(self):
        """Test ChildProfile with all fields."""
        profile = ChildProfile(
            name="Марійка",
            age=7,
            height_cm=128,
            gender="дівчинка",
            body_type="стандартна",
            height_history=[{"date": "2024-01", "height": 122}],
        )
        assert profile.name == "Марійка"
        assert profile.age == 7
        assert profile.height_cm == 128
        assert profile.gender == "дівчинка"

    def test_03_child_profile_age_validation_min(self):
        """Test age validation - minimum 0."""
        with pytest.raises(ValueError):
            ChildProfile(age=-1)

    def test_04_child_profile_age_validation_max(self):
        """Test age validation - maximum 18."""
        with pytest.raises(ValueError):
            ChildProfile(age=19)

    def test_05_child_profile_height_validation_min(self):
        """Test height validation - minimum 50."""
        with pytest.raises(ValueError):
            ChildProfile(height_cm=49)

    def test_06_child_profile_height_validation_max(self):
        """Test height validation - maximum 200."""
        with pytest.raises(ValueError):
            ChildProfile(height_cm=201)

    def test_07_child_profile_gender_literal(self):
        """Test gender literal values."""
        boy = ChildProfile(gender="хлопчик")
        girl = ChildProfile(gender="дівчинка")
        assert boy.gender == "хлопчик"
        assert girl.gender == "дівчинка"

    def test_08_child_profile_body_type_literal(self):
        """Test body type literal values."""
        for body_type in ["стандартна", "худорлява", "повненька"]:
            profile = ChildProfile(body_type=body_type)
            assert profile.body_type == body_type

    def test_09_child_profile_serialization(self):
        """Test model serialization to dict."""
        profile = ChildProfile(name="Тест", age=5)
        data = profile.model_dump()
        assert data["name"] == "Тест"
        assert data["age"] == 5

    def test_10_child_profile_from_dict(self):
        """Test model creation from dict."""
        data = {"name": "Іван", "age": 10, "height_cm": 140}
        profile = ChildProfile(**data)
        assert profile.name == "Іван"


# =============================================================================
# TEST 11-20: StylePreferences Model
# =============================================================================


class TestStylePreferences:
    """Tests for StylePreferences model."""

    def test_11_style_preferences_defaults(self):
        """Test StylePreferences with default empty lists."""
        prefs = StylePreferences()
        assert prefs.favorite_models == []
        assert prefs.preferred_styles == []
        assert prefs.favorite_colors == []
        assert prefs.avoided_colors == []
        assert prefs.fabric_preferences == []

    def test_12_style_preferences_favorite_models(self):
        """Test favorite models list."""
        prefs = StylePreferences(favorite_models=["Лагуна", "Ритм"])
        assert "Лагуна" in prefs.favorite_models
        assert len(prefs.favorite_models) == 2

    def test_13_style_preferences_colors(self):
        """Test color preferences."""
        prefs = StylePreferences(
            favorite_colors=["рожевий", "блакитний"],
            avoided_colors=["чорний"],
        )
        assert "рожевий" in prefs.favorite_colors
        assert "чорний" in prefs.avoided_colors

    def test_14_style_preferences_fabric(self):
        """Test fabric preferences."""
        prefs = StylePreferences(fabric_preferences=["бавовна", "льон"])
        assert "бавовна" in prefs.fabric_preferences

    def test_15_style_preferences_empty_lists_serialization(self):
        """Test that empty lists serialize correctly."""
        prefs = StylePreferences()
        data = prefs.model_dump()
        assert data["favorite_models"] == []
        assert isinstance(data["favorite_colors"], list)


# =============================================================================
# TEST 16-25: LogisticsInfo and CommerceInfo
# =============================================================================


class TestLogisticsAndCommerce:
    """Tests for LogisticsInfo and CommerceInfo models."""

    def test_16_logistics_defaults(self):
        """Test LogisticsInfo defaults."""
        info = LogisticsInfo()
        assert info.city is None
        assert info.delivery_type is None
        assert info.favorite_branch is None

    def test_17_logistics_full(self):
        """Test LogisticsInfo with all fields."""
        info = LogisticsInfo(
            city="Харків",
            delivery_type="nova_poshta",
            favorite_branch="Відділення №52",
        )
        assert info.city == "Харків"
        assert info.delivery_type == "nova_poshta"

    def test_18_logistics_delivery_types(self):
        """Test all delivery type literals."""
        for dtype in ["nova_poshta", "ukrposhta", "courier", "self_pickup"]:
            info = LogisticsInfo(delivery_type=dtype)
            assert info.delivery_type == dtype

    def test_19_commerce_defaults(self):
        """Test CommerceInfo defaults."""
        info = CommerceInfo()
        assert info.avg_check is None
        assert info.order_frequency is None
        assert info.discount_sensitive is False
        assert info.total_orders == 0

    def test_20_commerce_full(self):
        """Test CommerceInfo with all fields."""
        info = CommerceInfo(
            avg_check=1850.0,
            order_frequency="monthly",
            discount_sensitive=True,
            payment_preference="card_online",
            total_orders=5,
        )
        assert info.avg_check == 1850.0
        assert info.total_orders == 5

    def test_21_commerce_order_frequency_literals(self):
        """Test order frequency literals."""
        for freq in ["first_time", "rare", "monthly", "frequent"]:
            info = CommerceInfo(order_frequency=freq)
            assert info.order_frequency == freq

    def test_22_commerce_avg_check_validation(self):
        """Test avg_check must be >= 0."""
        with pytest.raises(ValueError):
            CommerceInfo(avg_check=-100)

    def test_23_commerce_total_orders_validation(self):
        """Test total_orders must be >= 0."""
        with pytest.raises(ValueError):
            CommerceInfo(total_orders=-1)


# =============================================================================
# TEST 24-35: UserProfile Model
# =============================================================================


class TestUserProfile:
    """Tests for UserProfile model."""

    def test_24_user_profile_minimal(self):
        """Test UserProfile with only required field."""
        profile = UserProfile(user_id="user_123")
        assert profile.user_id == "user_123"
        assert profile.child_profile is not None
        assert profile.completeness_score == 0.0

    def test_25_user_profile_full(self):
        """Test UserProfile with all nested models."""
        profile = UserProfile(
            user_id="user_456",
            child_profile=ChildProfile(name="Марія", age=7),
            style_preferences=StylePreferences(favorite_colors=["рожевий"]),
            logistics=LogisticsInfo(city="Київ"),
            commerce=CommerceInfo(total_orders=3),
        )
        assert profile.child_profile.name == "Марія"
        assert "рожевий" in profile.style_preferences.favorite_colors
        assert profile.logistics.city == "Київ"

    def test_26_user_profile_nested_defaults(self):
        """Test nested models have defaults."""
        profile = UserProfile(user_id="test")
        assert isinstance(profile.child_profile, ChildProfile)
        assert isinstance(profile.style_preferences, StylePreferences)
        assert isinstance(profile.logistics, LogisticsInfo)
        assert isinstance(profile.commerce, CommerceInfo)

    def test_27_user_profile_serialization(self):
        """Test full serialization."""
        profile = UserProfile(
            user_id="test",
            child_profile=ChildProfile(age=5),
        )
        data = profile.model_dump()
        assert data["user_id"] == "test"
        assert data["child_profile"]["age"] == 5

    def test_28_user_profile_completeness_range(self):
        """Test completeness_score must be 0-1."""
        with pytest.raises(ValueError):
            UserProfile(user_id="test", completeness_score=1.5)


# =============================================================================
# TEST 29-45: Fact Models (Fact, NewFact, UpdateFact)
# =============================================================================


class TestFactModels:
    """Tests for Fact, NewFact, UpdateFact models."""

    def test_29_new_fact_minimal(self):
        """Test NewFact with required fields."""
        fact = NewFact(
            content="Зріст дитини 128 см",
            fact_type="child_info",
            category="child",
            importance=0.9,
            surprise=0.8,
        )
        assert fact.content == "Зріст дитини 128 см"
        assert fact.importance == 0.9

    def test_30_new_fact_importance_validation_min(self):
        """Test importance must be >= 0."""
        with pytest.raises(ValueError):
            NewFact(
                content="test",
                fact_type="preference",
                category="general",
                importance=-0.1,
                surprise=0.5,
            )

    def test_31_new_fact_importance_validation_max(self):
        """Test importance must be <= 1."""
        with pytest.raises(ValueError):
            NewFact(
                content="test",
                fact_type="preference",
                category="general",
                importance=1.1,
                surprise=0.5,
            )

    def test_32_new_fact_surprise_validation(self):
        """Test surprise must be 0-1."""
        with pytest.raises(ValueError):
            NewFact(
                content="test",
                fact_type="preference",
                category="general",
                importance=0.5,
                surprise=1.5,
            )

    def test_33_new_fact_ttl_optional(self):
        """Test ttl_days is optional."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.6,
            surprise=0.5,
        )
        assert fact.ttl_days is None

    def test_34_new_fact_ttl_set(self):
        """Test ttl_days can be set."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.6,
            surprise=0.5,
            ttl_days=30,
        )
        assert fact.ttl_days == 30

    def test_35_new_fact_all_types(self):
        """Test all fact_type values."""
        types = ["preference", "constraint", "logistics", "behavior", "feedback", "child_info"]
        for ft in types:
            fact = NewFact(
                content="test",
                fact_type=ft,
                category="general",
                importance=0.5,
                surprise=0.5,
            )
            assert fact.fact_type == ft

    def test_36_new_fact_all_categories(self):
        """Test all category values."""
        categories = ["child", "style", "delivery", "payment", "product", "complaint", "general"]
        for cat in categories:
            fact = NewFact(
                content="test",
                fact_type="preference",
                category=cat,
                importance=0.5,
                surprise=0.5,
            )
            assert fact.category == cat

    def test_37_fact_full_model(self):
        """Test full Fact model."""
        fact = Fact(
            id=uuid4(),
            user_id="user_123",
            session_id="session_456",
            content="Улюблений колір рожевий",
            fact_type="preference",
            category="style",
            importance=0.8,
            surprise=0.6,
            confidence=0.9,
            is_active=True,
        )
        assert fact.user_id == "user_123"
        assert fact.is_active is True

    def test_38_fact_defaults(self):
        """Test Fact defaults."""
        fact = Fact(
            user_id="test",
            content="test",
            fact_type="preference",
            category="general",
        )
        assert fact.importance == 0.5
        assert fact.surprise == 0.5
        assert fact.confidence == 0.8
        assert fact.is_active is True

    def test_39_update_fact_model(self):
        """Test UpdateFact model."""
        update = UpdateFact(
            fact_id=uuid4(),
            new_content="Новий зріст 135 см",
            importance=0.95,
            surprise=0.9,
        )
        assert update.new_content == "Новий зріст 135 см"
        assert update.importance == 0.95

    def test_40_delete_fact_model(self):
        """Test DeleteFact model."""
        delete = DeleteFact(
            fact_id=uuid4(),
            reason="Outdated information",
        )
        assert delete.reason == "Outdated information"


# =============================================================================
# TEST 41-55: MemoryDecision Model
# =============================================================================


class TestMemoryDecision:
    """Tests for MemoryDecision model."""

    def test_41_memory_decision_empty(self):
        """Test empty MemoryDecision."""
        decision = MemoryDecision()
        assert decision.new_facts == []
        assert decision.updates == []
        assert decision.deletes == []
        assert decision.ignore_messages is False

    def test_42_memory_decision_with_new_facts(self):
        """Test MemoryDecision with new facts."""
        facts = [
            NewFact(
                content="Зріст 128 см",
                fact_type="child_info",
                category="child",
                importance=0.9,
                surprise=0.8,
            ),
        ]
        decision = MemoryDecision(new_facts=facts)
        assert len(decision.new_facts) == 1

    def test_43_memory_decision_with_updates(self):
        """Test MemoryDecision with updates."""
        updates = [
            UpdateFact(
                fact_id=uuid4(),
                new_content="Новий зріст",
                importance=0.9,
                surprise=0.9,
            ),
        ]
        decision = MemoryDecision(updates=updates)
        assert len(decision.updates) == 1

    def test_44_memory_decision_ignore_messages(self):
        """Test ignore_messages flag."""
        decision = MemoryDecision(
            ignore_messages=True,
            reasoning="No new information",
        )
        assert decision.ignore_messages is True
        assert decision.reasoning == "No new information"

    def test_45_memory_decision_profile_updates(self):
        """Test profile_updates dict."""
        decision = MemoryDecision(
            profile_updates={
                "child_profile": {"height_cm": 130},
                "logistics": {"city": "Київ"},
            }
        )
        assert decision.profile_updates["child_profile"]["height_cm"] == 130

    def test_46_memory_decision_complex(self):
        """Test complex MemoryDecision with all fields."""
        decision = MemoryDecision(
            new_facts=[
                NewFact(
                    content="test1",
                    fact_type="preference",
                    category="style",
                    importance=0.7,
                    surprise=0.6,
                ),
                NewFact(
                    content="test2",
                    fact_type="logistics",
                    category="delivery",
                    importance=0.8,
                    surprise=0.5,
                ),
            ],
            updates=[
                UpdateFact(
                    fact_id=uuid4(),
                    new_content="updated",
                    importance=0.9,
                    surprise=0.8,
                ),
            ],
            profile_updates={"commerce": {"total_orders": 5}},
            reasoning="Multiple facts extracted",
        )
        assert len(decision.new_facts) == 2
        assert len(decision.updates) == 1
        assert decision.reasoning is not None


# =============================================================================
# TEST 47-60: MemoryContext Model
# =============================================================================


class TestMemoryContext:
    """Tests for MemoryContext model."""

    def test_47_memory_context_empty(self):
        """Test empty MemoryContext."""
        ctx = MemoryContext()
        assert ctx.profile is None
        assert ctx.facts == []
        assert ctx.summary is None

    def test_48_memory_context_is_empty_true(self):
        """Test is_empty returns True for empty context."""
        ctx = MemoryContext()
        assert ctx.is_empty() is True

    def test_49_memory_context_is_empty_with_profile(self):
        """Test is_empty with profile that has data."""
        ctx = MemoryContext(
            profile=UserProfile(
                user_id="test",
                child_profile=ChildProfile(height_cm=128),
            )
        )
        assert ctx.is_empty() is False

    def test_50_memory_context_is_empty_with_facts(self):
        """Test is_empty with facts."""
        ctx = MemoryContext(
            facts=[
                Fact(
                    user_id="test",
                    content="test",
                    fact_type="preference",
                    category="general",
                ),
            ]
        )
        assert ctx.is_empty() is False

    def test_51_memory_context_to_prompt_empty(self):
        """Test to_prompt_block returns empty for empty context."""
        ctx = MemoryContext()
        assert ctx.to_prompt_block() == ""

    def test_52_memory_context_to_prompt_with_child(self):
        """Test to_prompt_block includes child info."""
        ctx = MemoryContext(
            profile=UserProfile(
                user_id="test",
                child_profile=ChildProfile(
                    name="Марія",
                    age=7,
                    height_cm=128,
                    gender="дівчинка",
                ),
            )
        )
        prompt = ctx.to_prompt_block()
        assert "Дитина:" in prompt
        assert "128 см" in prompt
        assert "7" in prompt

    def test_53_memory_context_to_prompt_with_city(self):
        """Test to_prompt_block includes city."""
        ctx = MemoryContext(
            profile=UserProfile(
                user_id="test",
                logistics=LogisticsInfo(city="Харків"),
            )
        )
        prompt = ctx.to_prompt_block()
        assert "Харків" in prompt

    def test_54_memory_context_to_prompt_with_facts(self):
        """Test to_prompt_block includes facts."""
        ctx = MemoryContext(
            facts=[
                Fact(
                    user_id="test",
                    content="Улюблений колір рожевий",
                    fact_type="preference",
                    category="style",
                ),
            ]
        )
        prompt = ctx.to_prompt_block()
        assert "Улюблений колір рожевий" in prompt

    def test_55_memory_context_to_prompt_limits_facts(self):
        """Test to_prompt_block limits facts to 10."""
        facts = [
            Fact(
                user_id="test",
                content=f"Fact {i}",
                fact_type="preference",
                category="general",
            )
            for i in range(15)
        ]
        ctx = MemoryContext(facts=facts)
        prompt = ctx.to_prompt_block()
        # Should have max 10 facts
        assert prompt.count("Fact") <= 10

    def test_56_memory_context_to_prompt_with_summary(self):
        """Test to_prompt_block includes summary."""
        ctx = MemoryContext(
            summary=MemorySummary(
                summary_type="user",
                summary_text="Постійний клієнт з Харкова",
            )
        )
        prompt = ctx.to_prompt_block()
        assert "Постійний клієнт з Харкова" in prompt


# =============================================================================
# TEST 57-65: MemorySummary Model
# =============================================================================


class TestMemorySummary:
    """Tests for MemorySummary model."""

    def test_57_memory_summary_minimal(self):
        """Test MemorySummary with required fields."""
        summary = MemorySummary(
            summary_type="user",
            summary_text="Test summary",
        )
        assert summary.summary_type == "user"
        assert summary.summary_text == "Test summary"

    def test_58_memory_summary_types(self):
        """Test all summary types."""
        for stype in ["user", "product", "session"]:
            summary = MemorySummary(
                summary_type=stype,
                summary_text="test",
            )
            assert summary.summary_type == stype

    def test_59_memory_summary_key_facts(self):
        """Test key_facts list."""
        summary = MemorySummary(
            summary_type="user",
            summary_text="test",
            key_facts=["Fact 1", "Fact 2", "Fact 3"],
        )
        assert len(summary.key_facts) == 3

    def test_60_memory_summary_facts_count(self):
        """Test facts_count."""
        summary = MemorySummary(
            summary_type="user",
            summary_text="test",
            facts_count=25,
        )
        assert summary.facts_count == 25

    def test_61_memory_summary_is_current_default(self):
        """Test is_current defaults to True."""
        summary = MemorySummary(
            summary_type="user",
            summary_text="test",
        )
        assert summary.is_current is True


# =============================================================================
# TEST 62-70: Edge Cases and Validation
# =============================================================================


class TestEdgeCases:
    """Edge case tests for memory models."""

    def test_62_empty_string_content(self):
        """Test fact with empty content."""
        # Empty content should be allowed (validation is business logic)
        fact = NewFact(
            content="",
            fact_type="preference",
            category="general",
            importance=0.5,
            surprise=0.5,
        )
        assert fact.content == ""

    def test_63_unicode_content(self):
        """Test Ukrainian text in content."""
        fact = NewFact(
            content="Донька носить тільки бавовняні речі 🌸",
            fact_type="constraint",
            category="style",
            importance=0.9,
            surprise=0.7,
        )
        assert "бавовняні" in fact.content
        assert "🌸" in fact.content

    def test_64_long_content(self):
        """Test very long content."""
        long_text = "A" * 10000
        fact = NewFact(
            content=long_text,
            fact_type="preference",
            category="general",
            importance=0.5,
            surprise=0.5,
        )
        assert len(fact.content) == 10000

    def test_65_special_characters_in_city(self):
        """Test special characters in city name."""
        info = LogisticsInfo(city="Кривий Ріг")
        assert info.city == "Кривий Ріг"

    def test_66_zero_importance(self):
        """Test zero importance is valid."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.0,
            surprise=0.5,
        )
        assert fact.importance == 0.0

    def test_67_boundary_importance(self):
        """Test boundary values for importance."""
        fact_min = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.0,
            surprise=0.5,
        )
        fact_max = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=1.0,
            surprise=0.5,
        )
        assert fact_min.importance == 0.0
        assert fact_max.importance == 1.0

    def test_68_rounding_importance(self):
        """Test importance is rounded to 2 decimal places."""
        fact = NewFact(
            content="test",
            fact_type="preference",
            category="general",
            importance=0.666666,
            surprise=0.5,
        )
        assert fact.importance == 0.67

    def test_69_none_session_id(self):
        """Test None session_id is allowed."""
        fact = Fact(
            user_id="test",
            session_id=None,
            content="test",
            fact_type="preference",
            category="general",
        )
        assert fact.session_id is None

    def test_70_uuid_serialization(self):
        """Test UUID serialization in Fact."""
        fact_id = uuid4()
        fact = Fact(
            id=fact_id,
            user_id="test",
            content="test",
            fact_type="preference",
            category="general",
        )
        data = fact.model_dump()
        assert data["id"] == fact_id
