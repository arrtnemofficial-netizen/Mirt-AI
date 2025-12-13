"""
CONTRACT: AgentResponse schema validation.

Ensures the core AgentResponse structure doesn't change unexpectedly.
External systems (ManyChat, Telegram) depend on this contract.
"""

import pytest


@pytest.mark.contract
@pytest.mark.critical
class TestAgentResponseContract:
    """Verify AgentResponse schema contract is maintained."""

    def test_agent_response_has_required_fields(self):
        """AgentResponse must have all required fields."""
        from src.core.models import AgentResponse

        # Check required fields exist in model
        required_fields = ["messages", "products", "metadata"]
        model_fields = AgentResponse.model_fields.keys()

        for field in required_fields:
            assert field in model_fields, (
                f"CONTRACT: AgentResponse missing required field '{field}'"
            )

    def test_agent_response_messages_is_list(self):
        """AgentResponse.messages must be a list."""
        from src.core.models import AgentResponse, Message

        response = AgentResponse(
            event="simple_answer",
            messages=[Message(type="text", content="Test")],
            products=[],
            metadata={},
        )

        assert isinstance(response.messages, list), "CONTRACT: messages must be a list"

    def test_agent_response_products_is_list(self):
        """AgentResponse.products must be a list."""
        from src.core.models import AgentResponse, Message

        response = AgentResponse(
            event="simple_answer",
            messages=[Message(type="text", content="Test")],
            products=[],
            metadata={},
        )

        assert isinstance(response.products, list), "CONTRACT: products must be a list"

    def test_message_type_must_be_text_or_image(self):
        """Message.type must be 'text' or 'image'."""
        from src.core.models import Message

        # Valid types
        text_msg = Message(type="text", content="Hello")
        assert text_msg.type == "text"

        image_msg = Message(type="image", content="https://example.com/img.jpg")
        assert image_msg.type == "image"

    def test_product_has_required_fields(self):
        """Product model must have required fields."""
        from src.core.models import Product

        required_fields = ["id", "name", "price"]
        model_fields = Product.model_fields.keys()

        for field in required_fields:
            assert field in model_fields, f"CONTRACT: Product missing required field '{field}'"

    def test_metadata_has_expected_fields(self):
        """Metadata model has expected optional fields."""
        from src.core.models import Metadata

        # Use actual field names from Metadata
        expected_fields = ["current_state", "intent", "session_id", "escalation_level"]
        model_fields = Metadata.model_fields.keys()

        for field in expected_fields:
            assert field in model_fields, f"CONTRACT: Metadata missing expected field '{field}'"


@pytest.mark.contract
@pytest.mark.critical
class TestSupportResponseContract:
    """Verify SupportResponse (LLM output) schema contract."""

    def test_support_response_has_required_fields(self):
        """SupportResponse must have core fields."""
        from src.agents.pydantic.models import SupportResponse

        # Use actual field names from SupportResponse
        required_fields = ["messages", "event", "metadata"]
        model_fields = SupportResponse.model_fields.keys()

        for field in required_fields:
            assert field in model_fields, (
                f"CONTRACT: SupportResponse missing required field '{field}'"
            )

    def test_support_response_messages_structure(self):
        """SupportResponse.messages must be list of MessageItem."""
        from src.agents.pydantic.models import MessageItem, SupportResponse

        response = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(type="text", content="Привіт!")],
            metadata={},
        )

        assert len(response.messages) > 0
        assert isinstance(response.messages[0], MessageItem)

    def test_support_response_has_deliberation(self):
        """SupportResponse should have optional deliberation field."""
        from src.agents.pydantic.models import SupportResponse

        assert "deliberation" in SupportResponse.model_fields, (
            "CONTRACT: SupportResponse should have 'deliberation' field for multi-role pattern"
        )


@pytest.mark.contract
@pytest.mark.critical
class TestProductMatchContract:
    """Verify ProductMatch schema contract."""

    def test_product_match_has_required_fields(self):
        """ProductMatch must have product identification fields."""
        from src.agents.pydantic.models import ProductMatch

        required_fields = ["id", "name", "price"]
        model_fields = ProductMatch.model_fields.keys()

        for field in required_fields:
            assert field in model_fields, f"CONTRACT: ProductMatch missing required field '{field}'"

    def test_product_match_structure(self):
        """ProductMatch creates valid product objects."""
        from src.agents.pydantic.models import ProductMatch

        # Valid product
        product = ProductMatch(
            id=1,
            name="Test Product",
            price=100.0,
        )
        assert product.name == "Test Product"
