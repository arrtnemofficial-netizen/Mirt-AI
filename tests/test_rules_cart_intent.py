"""
Unit tests for cart_intent detection rules.
===========================================
Tests detection of add-to-cart keywords.
"""

import pytest

from src.agents.langgraph.rules.cart_intent import detect_add_to_cart


class TestCartIntentDetection:
    """Test add-to-cart intent detection."""

    def test_ukrainian_keywords(self):
        """Ukrainian keywords should trigger detection."""
        assert detect_add_to_cart("Ще один товар") is True
        assert detect_add_to_cart("Додай ще") is True
        assert detect_add_to_cart("Також цей") is True
        assert detect_add_to_cart("І ще") is True

    def test_russian_variants(self):
        """Russian variants should work."""
        assert detect_add_to_cart("Еще один") is True
        assert detect_add_to_cart("Добавь") is True

    def test_symbols(self):
        """Symbols like '+' should work."""
        assert detect_add_to_cart("+") is True
        assert detect_add_to_cart("Ще +") is True

    def test_no_keywords(self):
        """No add-to-cart keywords → no detection."""
        assert detect_add_to_cart("Хочу купити") is False
        assert detect_add_to_cart("Дякую") is False

    def test_empty_string(self):
        """Empty string should not trigger detection."""
        assert detect_add_to_cart("") is False

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert detect_add_to_cart("ЩЕ") is True
        assert detect_add_to_cart("ДОДАЙ") is True

    def test_partial_match(self):
        """Partial matches should work."""
        assert detect_add_to_cart("Ще один товар") is True
        assert detect_add_to_cart("Додай ще один") is True

