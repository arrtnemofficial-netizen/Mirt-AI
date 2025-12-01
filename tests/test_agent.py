"""
Tests for PydanticAI agents (run_support, run_vision).
=======================================================
Updated for new architecture with PydanticAI 1.23+
"""

import pytest
from unittest.mock import patch, AsyncMock

from src.agents import (
    AgentDeps,
    SupportResponse,
    VisionResponse,
    MessageItem,
    ResponseMetadata,
    create_deps_from_state,
)
from src.core.models import Product, Message, Metadata, AgentResponse


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_deps() -> AgentDeps:
    """Create sample AgentDeps for testing."""
    return AgentDeps(
        session_id="test-session-123",
        current_state="STATE_0_INIT",
        channel="telegram",
    )


@pytest.fixture
def sample_vision_deps() -> AgentDeps:
    """Create sample AgentDeps with image for vision testing."""
    return AgentDeps(
        session_id="test-vision-456",
        current_state="STATE_2_VISION",
        channel="telegram",
        has_image=True,
        image_url="https://example.com/test.jpg",
    )


# =============================================================================
# AGENT DEPS TESTS
# =============================================================================


class TestAgentDeps:
    """Tests for AgentDeps data class."""

    def test_agent_deps_creation(self, sample_deps: AgentDeps):
        """Test AgentDeps creates correctly."""
        assert sample_deps.session_id == "test-session-123"
        assert sample_deps.current_state == "STATE_0_INIT"
        assert sample_deps.channel == "telegram"

    def test_create_deps_from_state(self):
        """Test creating deps from LangGraph state."""
        state = {
            "session_id": "state-session",
            "current_state": "STATE_1_DISCOVERY",
            "metadata": {"channel": "instagram", "customer_name": "Марія"},
            "image_url": "https://example.com/photo.jpg",
            "has_image": True,
        }

        deps = create_deps_from_state(state)

        assert deps.session_id == "state-session"
        assert deps.current_state == "STATE_1_DISCOVERY"
        assert deps.channel == "instagram"
        assert deps.customer_name == "Марія"
        assert deps.has_image is True
        assert deps.image_url == "https://example.com/photo.jpg"

    def test_deps_defaults(self):
        """Test AgentDeps default values."""
        deps = AgentDeps(session_id="test")

        assert deps.session_id == "test"
        assert deps.current_state == "STATE_0_INIT"
        assert deps.channel == "instagram"  # Default is instagram
        assert deps.language == "uk"
        assert deps.has_image is False


# =============================================================================
# RESPONSE MODELS TESTS
# =============================================================================


class TestSupportResponse:
    """Tests for SupportResponse model."""

    def test_support_response_creation(self):
        """Test creating valid SupportResponse."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Вітаю! Чим допомогти?")],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

        assert response.event == "simple_answer"
        assert len(response.messages) == 1
        assert response.messages[0].content == "Вітаю! Чим допомогти?"
        assert response.metadata.current_state == "STATE_1_DISCOVERY"

    def test_support_response_with_products(self):
        """Test SupportResponse with products."""
        from src.agents import ProductMatch

        response = SupportResponse(
            event="multi_option",
            messages=[MessageItem(content="Ось наші сукні:")],
            products=[
                ProductMatch(
                    id=123,
                    name="Сукня Еліт",
                    price=1300,
                    size="122",
                    color="рожева",
                    photo_url="https://cdn.example.com/1.jpg",
                )
            ],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_4_OFFER",
                intent="SIZE_HELP",
                escalation_level="NONE",
            ),
        )

        assert len(response.products) == 1
        assert response.products[0].name == "Сукня Еліт"
        assert response.products[0].price == 1300


class TestVisionResponse:
    """Tests for VisionResponse model."""

    def test_vision_response_minimal(self):
        """Test minimal VisionResponse."""
        response = VisionResponse(
            reply_to_user="Це схоже на сукню Анна",
            confidence=0.85,
            needs_clarification=False,
        )

        assert response.confidence == 0.85
        assert response.needs_clarification is False

    def test_vision_response_with_product(self):
        """Test VisionResponse with identified product."""
        from src.agents import ProductMatch

        response = VisionResponse(
            reply_to_user="Знайшла товар!",
            confidence=0.95,
            needs_clarification=False,
            identified_product=ProductMatch(
                id=456,
                name="Тренч Парижанка",
                price=2500,
                size="128",
                color="бежевий",
                photo_url="https://cdn.example.com/trench.jpg",
            ),
        )

        assert response.identified_product is not None
        assert response.identified_product.name == "Тренч Парижанка"


# =============================================================================
# CORE MODELS TESTS
# =============================================================================


class TestCoreModels:
    """Tests for core models (Product, Message, Metadata)."""

    def test_product_with_id(self):
        """Test Product model with id field."""
        product = Product(
            id=123,
            name="Тестовий товар",
            size="122",
            color="червоний",
            price=100.0,
            photo_url="https://example.com/1.jpg",
        )

        assert product.id == 123
        assert product.product_id == 123  # backward compatibility
        assert product.name == "Тестовий товар"

    def test_product_from_legacy(self):
        """Test Product.from_legacy with product_id."""
        legacy_data = {
            "product_id": 456,
            "name": "Legacy Product",
            "price": 200.0,
            "photo_url": "https://example.com/2.jpg",
        }

        product = Product.from_legacy(legacy_data)

        assert product.id == 456
        assert product.name == "Legacy Product"

    def test_message_creation(self):
        """Test Message model."""
        msg = Message(content="Привіт!")
        assert msg.type == "text"
        assert msg.content == "Привіт!"

    def test_metadata_normalizes_state(self):
        """Test Metadata normalizes state strings."""
        meta = Metadata(current_state="state0_init")
        assert meta.current_state == "STATE_0_INIT"

    def test_metadata_normalizes_intent(self):
        """Test Metadata normalizes intent strings."""
        meta = Metadata(intent="greeting_only")
        assert meta.intent == "GREETING_ONLY"

    def test_agent_response_creation(self):
        """Test AgentResponse model."""
        response = AgentResponse(
            event="simple_answer",
            messages=[Message(content="Тест")],
            products=[],
            metadata=Metadata(
                session_id="test",
                current_state="STATE_0_INIT",
            ),
        )

        assert response.event == "simple_answer"
        assert len(response.messages) == 1
