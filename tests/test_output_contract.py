"""
OUTPUT_CONTRACT Freeze Tests.
==============================
These tests ensure the response schemas (SupportResponse, VisionResponse)
do NOT change without explicit review.

RULE: Schema changes require incrementing version and migration plan.
"""

import pytest
from pydantic import BaseModel

from src.agents.pydantic.models import (
    SupportResponse,
    VisionResponse,
    ProductMatch as IdentifiedProduct,
    ResponseMetadata,
    MessageItem as ChatMessage,
)


# =============================================================================
# FROZEN SCHEMA DEFINITIONS
# =============================================================================
# These are the "golden" field sets that MUST NOT change without review.

SUPPORT_RESPONSE_REQUIRED_FIELDS = {
    "event",
    "messages",
}

SUPPORT_RESPONSE_OPTIONAL_FIELDS = {
    "products",
    "metadata",
}

VISION_RESPONSE_REQUIRED_FIELDS = {
    "reply_to_user",
    "confidence",
    "needs_clarification",
}

VISION_RESPONSE_OPTIONAL_FIELDS = {
    "identified_product",
    "clarification_question",
    "alternative_products",
}

RESPONSE_METADATA_FIELDS = {
    "current_state",
    "intent",
    "escalation_level",
}

IDENTIFIED_PRODUCT_FIELDS = {
    "name",
    "price",
}


# =============================================================================
# SCHEMA FREEZE TESTS
# =============================================================================

class TestSupportResponseContract:
    """SupportResponse schema must match frozen definition."""

    def test_required_fields_present(self):
        """All required fields must be present."""
        model_fields = set(SupportResponse.model_fields.keys())
        for field in SUPPORT_RESPONSE_REQUIRED_FIELDS:
            assert field in model_fields, f"Missing required field: {field}"

    def test_optional_fields_present(self):
        """All optional fields must be present."""
        model_fields = set(SupportResponse.model_fields.keys())
        for field in SUPPORT_RESPONSE_OPTIONAL_FIELDS:
            assert field in model_fields, f"Missing optional field: {field}"

    def test_no_unexpected_required_fields(self):
        """No unexpected required fields should be added."""
        all_expected = SUPPORT_RESPONSE_REQUIRED_FIELDS | SUPPORT_RESPONSE_OPTIONAL_FIELDS
        model_fields = set(SupportResponse.model_fields.keys())
        
        unexpected = model_fields - all_expected
        # Allow new optional fields, but warn
        for field in unexpected:
            field_info = SupportResponse.model_fields[field]
            # Check if it's optional (has default or is not required)
            is_optional = not field_info.is_required()
            assert is_optional, \
                f"Unexpected required field added: {field}. Schema changes require review!"

    def test_event_field_is_string_like(self):
        """Event field must be string-like (Literal or str)."""
        field_info = SupportResponse.model_fields["event"]
        annotation_str = str(field_info.annotation).lower()
        # Literal[...] is also string-compatible
        assert "str" in annotation_str or "literal" in annotation_str

    def test_messages_field_is_list(self):
        """Messages field must be list."""
        field_info = SupportResponse.model_fields["messages"]
        assert "list" in str(field_info.annotation).lower()


class TestVisionResponseContract:
    """VisionResponse schema must match frozen definition."""

    def test_required_fields_present(self):
        """All required fields must be present."""
        model_fields = set(VisionResponse.model_fields.keys())
        for field in VISION_RESPONSE_REQUIRED_FIELDS:
            assert field in model_fields, f"Missing required field: {field}"

    def test_optional_fields_present(self):
        """All optional fields must be present."""
        model_fields = set(VisionResponse.model_fields.keys())
        for field in VISION_RESPONSE_OPTIONAL_FIELDS:
            assert field in model_fields, f"Missing optional field: {field}"

    def test_confidence_is_float(self):
        """Confidence must be float."""
        field_info = VisionResponse.model_fields["confidence"]
        assert "float" in str(field_info.annotation).lower()

    def test_needs_clarification_is_bool(self):
        """needs_clarification must be bool."""
        field_info = VisionResponse.model_fields["needs_clarification"]
        assert "bool" in str(field_info.annotation).lower()


class TestResponseMetadataContract:
    """ResponseMetadata schema must match frozen definition."""

    def test_required_fields_present(self):
        """All metadata fields must be present."""
        model_fields = set(ResponseMetadata.model_fields.keys())
        for field in RESPONSE_METADATA_FIELDS:
            assert field in model_fields, f"Missing metadata field: {field}"


class TestIdentifiedProductContract:
    """IdentifiedProduct schema must match frozen definition."""

    def test_required_fields_present(self):
        """All product fields must be present."""
        model_fields = set(IdentifiedProduct.model_fields.keys())
        for field in IDENTIFIED_PRODUCT_FIELDS:
            assert field in model_fields, f"Missing product field: {field}"


# =============================================================================
# SERIALIZATION TESTS
# =============================================================================

class TestSerialization:
    """Test that models serialize correctly."""

    def test_support_response_to_dict(self):
        """SupportResponse should serialize to dict."""
        response = SupportResponse(
            event="simple_answer",
            messages=[ChatMessage(type="text", content="Test")],
            metadata=ResponseMetadata(
                current_state="STATE_0_INIT",
                intent="GREETING_ONLY",
            ),
        )
        data = response.model_dump()
        
        assert "event" in data
        assert "messages" in data
        assert data["event"] == "simple_answer"

    def test_vision_response_to_dict(self):
        """VisionResponse should serialize to dict."""
        response = VisionResponse(
            reply_to_user="Test",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(name="Test", price=1000),
        )
        data = response.model_dump()
        
        assert "reply_to_user" in data
        assert "confidence" in data
        assert data["confidence"] == 0.9

    def test_support_response_from_dict(self):
        """SupportResponse should deserialize from dict."""
        data = {
            "event": "simple_answer",
            "messages": [{"type": "text", "content": "Test"}],
            "metadata": {"current_state": "STATE_0_INIT", "intent": "GREETING_ONLY"},
        }
        response = SupportResponse.model_validate(data)
        
        assert response.event == "simple_answer"
        assert len(response.messages) == 1

    def test_vision_response_from_dict(self):
        """VisionResponse should deserialize from dict."""
        data = {
            "reply_to_user": "Test",
            "confidence": 0.8,
            "needs_clarification": True,
        }
        response = VisionResponse.model_validate(data)
        
        assert response.reply_to_user == "Test"
        assert response.confidence == 0.8


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

class TestBackwardCompatibility:
    """Test that old response formats still work."""

    def test_support_response_minimal(self):
        """Minimal SupportResponse should work."""
        response = SupportResponse(
            event="simple_answer",
            messages=[ChatMessage(type="text", content="Hi")],
            metadata=ResponseMetadata(current_state="STATE_0_INIT", intent="GREETING_ONLY"),
        )
        assert response.event == "simple_answer"

    def test_vision_response_minimal(self):
        """Minimal VisionResponse should work."""
        response = VisionResponse(
            reply_to_user="Test",
            confidence=0.5,
            needs_clarification=False,
        )
        assert response.confidence == 0.5

    def test_vision_response_with_product(self):
        """VisionResponse with product should work."""
        response = VisionResponse(
            reply_to_user="Found!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Test Product",
                price=2000,
                photo_url="https://example.com/photo.jpg",
                color="рожевий",
            ),
        )
        assert response.identified_product.name == "Test Product"
        assert response.identified_product.price == 2000
