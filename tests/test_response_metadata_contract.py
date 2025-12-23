"""
Regression test for ResponseMetadata escalation_level contract compliance.
========================================================================
Ensures that SupportResponse metadata never breaks parsing.
"""

import pytest

from src.agents.pydantic.models import ResponseMetadata, SupportResponse


class TestResponseMetadataContract:
    """Test that ResponseMetadata escalation_level normalization works correctly."""

    def test_normalize_soft_to_l1(self):
        """SOFT should normalize to L1."""
        metadata = ResponseMetadata(escalation_level="SOFT")
        assert metadata.escalation_level == "L1"

    def test_normalize_hard_to_l2(self):
        """HARD should normalize to L2."""
        metadata = ResponseMetadata(escalation_level="HARD")
        assert metadata.escalation_level == "L2"

    def test_normalize_case_insensitive(self):
        """Normalization should be case-insensitive."""
        assert ResponseMetadata(escalation_level="soft").escalation_level == "L1"
        assert ResponseMetadata(escalation_level="HARD").escalation_level == "L2"

    def test_support_response_with_soft_parses(self):
        """SupportResponse with SOFT in metadata should parse correctly."""
        response = SupportResponse(
            event="simple_answer",
            messages=[{"type": "text", "content": "test"}],
            metadata={
                "session_id": "test123",
                "current_state": "STATE_0_INIT",
                "intent": "PHOTO_IDENT",
                "escalation_level": "SOFT",  # Should normalize to L1
            },
        )
        assert response.metadata.escalation_level == "L1"

    def test_support_response_with_hard_parses(self):
        """SupportResponse with HARD in metadata should parse correctly."""
        response = SupportResponse(
            event="escalation",
            messages=[{"type": "text", "content": "test"}],
            metadata={
                "session_id": "test123",
                "current_state": "STATE_0_INIT",
                "intent": "PHOTO_IDENT",
                "escalation_level": "HARD",  # Should normalize to L2
            },
        )
        assert response.metadata.escalation_level == "L2"

