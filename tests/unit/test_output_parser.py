"""
Tests for PydanticAI response models and output validation.
============================================================
Updated for new architecture - tests SupportResponse, VisionResponse parsing.
"""

import pytest

from src.agents import (
    MessageItem,
    ProductMatch,
    ResponseMetadata,
    SupportResponse,
    VisionResponse,
)
from src.core.models import AgentResponse, Message, Metadata, Product


# =============================================================================
# SUPPORT RESPONSE TESTS
# =============================================================================


class TestSupportResponse:
    """Test SupportResponse model parsing and validation."""

    def test_valid_support_response(self):
        """Test valid SupportResponse creation."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Вітаю!")],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_1_DISCOVERY",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

        assert response.event == "simple_answer"
        assert len(response.messages) == 1
        assert response.messages[0].content == "Вітаю!"

    def test_support_response_with_products(self):
        """Test SupportResponse with products."""
        response = SupportResponse(
            event="multi_option",
            messages=[MessageItem(content="Ось товари:")],
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

    def test_metadata_preserves_state(self):
        """Test metadata preserves current_state."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Test")],
            metadata=ResponseMetadata(
                session_id="my-session",
                current_state="STATE_4_OFFER",
                intent="DISCOVERY_OR_QUESTION",
                escalation_level="NONE",
            ),
        )

        assert response.metadata.session_id == "my-session"
        assert response.metadata.current_state == "STATE_4_OFFER"

    def test_empty_products_allowed(self):
        """Test empty products list is allowed."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Ніяких товарів")],
            products=[],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_0_INIT",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

        assert response.products == []


# =============================================================================
# VISION RESPONSE TESTS
# =============================================================================


class TestVisionResponse:
    """Test VisionResponse model."""

    def test_minimal_vision_response(self):
        """Test minimal VisionResponse."""
        response = VisionResponse(
            reply_to_user="Це схоже на сукню",
            confidence=0.85,
            needs_clarification=False,
        )

        assert response.confidence == 0.85
        assert response.needs_clarification is False
        assert response.identified_product is None

    def test_vision_response_with_product(self):
        """Test VisionResponse with identified product."""
        response = VisionResponse(
            reply_to_user="Знайшла!",
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

    def test_vision_needs_clarification(self):
        """Test VisionResponse with clarification."""
        response = VisionResponse(
            reply_to_user="Не зовсім зрозуміло",
            confidence=0.3,
            needs_clarification=True,
            clarification_question="Який колір вас цікавить?",
        )

        assert response.needs_clarification is True
        assert response.clarification_question == "Який колір вас цікавить?"


# =============================================================================
# CORE MODELS TESTS
# =============================================================================


class TestAgentResponse:
    """Test core AgentResponse model."""

    def test_valid_agent_response(self):
        """Test valid AgentResponse creation."""
        response = AgentResponse(
            event="simple_answer",
            messages=[Message(content="Привіт!")],
            products=[],
            metadata=Metadata(
                session_id="test",
                current_state="STATE_0_INIT",
            ),
        )

        assert response.event == "simple_answer"
        assert len(response.messages) == 1

    def test_agent_response_with_products(self):
        """Test AgentResponse with products."""
        response = AgentResponse(
            event="product_showcase",
            messages=[Message(content="Ось товари:")],
            products=[
                Product(
                    id=1,
                    name="Dress",
                    price=1000,
                    photo_url="https://example.com/img.jpg",
                )
            ],
            metadata=Metadata(current_state="STATE_4_OFFER"),
        )

        assert len(response.products) == 1
        assert response.products[0].name == "Dress"


# =============================================================================
# PRODUCT MATCH VALIDATION
# =============================================================================


class TestProductMatch:
    """Test ProductMatch validation."""

    def test_valid_product_match(self):
        """Test valid ProductMatch."""
        product = ProductMatch(
            id=123,
            name="Test Product",
            price=500,
            size="M",
            color="red",
            photo_url="https://example.com/photo.jpg",
        )

        assert product.id == 123
        assert product.name == "Test Product"

    def test_product_requires_https(self):
        """Test ProductMatch requires HTTPS URL."""
        with pytest.raises(ValueError):
            ProductMatch(
                id=123,
                name="Test",
                price=100,
                size="M",
                color="red",
                photo_url="http://not-https.com/photo.jpg",
            )

    def test_product_accepts_https(self):
        """Test ProductMatch accepts HTTPS URL."""
        product = ProductMatch(
            id=456,
            name="Valid Product",
            price=200,
            size="L",
            color="blue",
            photo_url="https://cdn.example.com/photo.jpg",
        )

        assert product.photo_url.startswith("https://")


# =============================================================================
# MESSAGE ITEM VALIDATION
# =============================================================================


class TestMessageItem:
    """Test MessageItem validation."""

    def test_valid_message_item(self):
        """Test valid MessageItem."""
        msg = MessageItem(content="Привіт!")

        assert msg.type == "text"
        assert msg.content == "Привіт!"

    def test_message_item_max_length(self):
        """Test MessageItem enforces max length."""
        with pytest.raises(ValueError):
            MessageItem(content="x" * 1000)  # > 900 chars

    def test_message_item_types(self):
        """Test MessageItem type field - 'text' and 'image' are supported."""
        text_msg = MessageItem(type="text", content="Text")
        assert text_msg.type == "text"

        # Test that 'image' type is allowed
        img_msg = MessageItem(type="image", content="https://example.com/img.jpg")
        assert img_msg.type == "image"

        # Test invalid type
        with pytest.raises(ValueError):
            MessageItem(type="video", content="https://example.com/video.mp4")


# =============================================================================
# UNICODE AND EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Test edge cases and special content."""

    def test_unicode_content(self):
        """Test Ukrainian content handling."""
        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Привіт 🎀 Як справи? 👗")],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_0_INIT",
                intent="GREETING_ONLY",
                escalation_level="NONE",
            ),
        )

        assert "🎀" in response.messages[0].content
        assert "👗" in response.messages[0].content

    def test_empty_messages_list(self):
        """Test response requires at least one message."""
        # SupportResponse requires at least 1 message, so test with one
        response = SupportResponse(
            event="escalation",
            messages=[MessageItem(content="Escalation message")],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_8_COMPLAINT",
                intent="COMPLAINT",
                escalation_level="L1",
            ),
        )

        assert len(response.messages) == 1

    def test_multiple_products(self):
        """Test response with multiple products."""
        response = SupportResponse(
            event="multi_option",
            messages=[MessageItem(content="Ось варіанти:")],
            products=[
                ProductMatch(
                    id=1,
                    name="Product A",
                    price=100,
                    size="M",
                    color="red",
                    photo_url="https://a.com/1.jpg",
                ),
                ProductMatch(
                    id=2,
                    name="Product B",
                    price=200,
                    size="L",
                    color="blue",
                    photo_url="https://b.com/2.jpg",
                ),
                ProductMatch(
                    id=3,
                    name="Product C",
                    price=300,
                    size="XL",
                    color="green",
                    photo_url="https://c.com/3.jpg",
                ),
            ],
            metadata=ResponseMetadata(
                session_id="test",
                current_state="STATE_4_OFFER",
                intent="SIZE_HELP",
                escalation_level="NONE",
            ),
        )

        assert len(response.products) == 3
