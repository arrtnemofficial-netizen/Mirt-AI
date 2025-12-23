"""
Regression test for escalation_level contract compliance.
========================================================
Ensures that vision escalation never breaks Metadata parsing.
"""

import pytest

from src.core.models import Metadata


class TestEscalationLevelContract:
    """Test that escalation_level normalization works correctly."""

    def test_normalize_soft_to_l1(self):
        """SOFT should normalize to L1."""
        metadata = Metadata(escalation_level="SOFT")
        assert metadata.escalation_level == "L1"

    def test_normalize_hard_to_l2(self):
        """HARD should normalize to L2."""
        metadata = Metadata(escalation_level="HARD")
        assert metadata.escalation_level == "L2"

    def test_normalize_case_insensitive(self):
        """Normalization should be case-insensitive."""
        assert Metadata(escalation_level="soft").escalation_level == "L1"
        assert Metadata(escalation_level="HARD").escalation_level == "L2"
        assert Metadata(escalation_level="Soft").escalation_level == "L1"

    def test_normalize_empty_to_none(self):
        """Empty/None should normalize to NONE."""
        assert Metadata(escalation_level="").escalation_level == "NONE"
        assert Metadata(escalation_level=None).escalation_level == "NONE"

    def test_valid_levels_unchanged(self):
        """Valid levels (NONE, L1, L2, L3) should remain unchanged."""
        assert Metadata(escalation_level="NONE").escalation_level == "NONE"
        assert Metadata(escalation_level="L1").escalation_level == "L1"
        assert Metadata(escalation_level="L2").escalation_level == "L2"
        assert Metadata(escalation_level="L3").escalation_level == "L3"

    def test_unknown_value_normalizes_to_none(self):
        """Unknown values should normalize to NONE (production safety)."""
        metadata = Metadata(escalation_level="INVALID")
        assert metadata.escalation_level == "NONE"

    def test_vision_escalation_response_parses(self):
        """Test that vision escalation response (with SOFT) parses correctly."""
        # Simulate what vision.py returns (before fix it was "SOFT", now should be "L1")
        response_data = {
            "session_id": "test123",
            "current_state": "STATE_0_INIT",
            "intent": "PHOTO_IDENT",
            "escalation_level": "L1",  # Contract-compliant
            "notes": "escalation_mode=SOFT",  # UX mode stored separately
        }
        
        metadata = Metadata(**response_data)
        assert metadata.escalation_level == "L1"
        assert metadata.notes == "escalation_mode=SOFT"

    def test_backward_compatibility_soft(self):
        """Test backward compatibility: if legacy code writes SOFT, it should work."""
        # This simulates old code that might still write "SOFT"
        metadata = Metadata(escalation_level="SOFT")
        assert metadata.escalation_level == "L1"  # Normalized, not crashed

    def test_backward_compatibility_hard(self):
        """Test backward compatibility: if legacy code writes HARD, it should work."""
        metadata = Metadata(escalation_level="HARD")
        assert metadata.escalation_level == "L2"  # Normalized, not crashed

