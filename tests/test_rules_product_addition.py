"""
Unit tests for product_addition detection rules.
================================================
Tests detection of product addition intent vs payment proof.
"""

import pytest

from src.agents.langgraph.rules.product_addition import detect_product_addition_intent
from src.agents.langgraph.rules.payment_proof import detect_payment_proof


class TestProductAdditionDetection:
    """Test product addition intent detection with various inputs."""

    def test_product_addition_keywords(self):
        """Product addition keywords should be detected."""
        assert detect_product_addition_intent("А можна ще додати") is True
        assert detect_product_addition_intent("Цей костюм") is True
        assert detect_product_addition_intent("Хочу ще цей костюм") is True
        assert detect_product_addition_intent("Додати ще один") is True
        assert detect_product_addition_intent("Можна додати") is True

    def test_payment_proof_not_product_addition(self):
        """Payment proof keywords should NOT be detected as product addition."""
        assert detect_product_addition_intent("Оплатила") is False
        assert detect_product_addition_intent("Надіслав скрін") is False
        assert detect_product_addition_intent("Ось квитанцію") is False

    def test_empty_string(self):
        """Empty string should not be product addition."""
        assert detect_product_addition_intent("") is False

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert detect_product_addition_intent("ЦЕЙ КОСТЮМ") is True
        assert detect_product_addition_intent("ДОДАТИ ЩЕ") is True

    def test_russian_variants(self):
        """Russian variants should work."""
        assert detect_product_addition_intent("Этот костюм") is True
        assert detect_product_addition_intent("Добавить еще") is True
        assert detect_product_addition_intent("Хочу этот") is True


class TestPaymentProofVsProductAddition:
    """Test that payment proof detection correctly excludes product addition."""

    def test_product_addition_not_payment_proof(self):
        """Product addition intent should NOT be detected as payment proof."""
        # These should be False (product addition, not payment proof)
        assert detect_payment_proof("А можна ще додати", has_image=True) is False
        assert detect_payment_proof("Цей костюм", has_image=True) is False
        assert detect_payment_proof("Хочу ще цей костюм", has_image=True) is False
        assert detect_payment_proof("Додати ще один", has_image=True) is False

    def test_payment_proof_still_works(self):
        """Payment proof detection should still work for actual payment proof."""
        # These should be True (actual payment proof)
        assert detect_payment_proof("Оплатила", has_image=True) is True
        assert detect_payment_proof("Надіслав скрін", has_image=True) is True
        assert detect_payment_proof("Ось квитанцію", has_image=True) is True
        # Empty text with image should still be payment proof (conservative)
        assert detect_payment_proof("", has_image=True) is True

    def test_product_addition_with_payment_keyword(self):
        """If text contains both product addition and payment keywords, product addition wins."""
        # Edge case: "додати оплату" - should be product addition, not payment proof
        # But this is unlikely in real scenarios
        assert detect_product_addition_intent("Додати оплату") is True
        # However, if it has payment keyword, it might still be payment proof
        # This is a design decision - product addition takes priority
        assert detect_payment_proof("Додати оплату", has_image=True) is False

    def test_empty_text_with_image(self):
        """Empty text with image should be payment proof (conservative approach)."""
        # This is the conservative approach - if no text, assume payment proof
        assert detect_payment_proof("", has_image=True) is True

