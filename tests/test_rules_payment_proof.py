"""
Unit tests for payment_proof detection rules.
==============================================
Tests edge cases: UA/RU, "скрин/скрін", URL, image flag.
"""

import pytest

from src.agents.langgraph.rules.payment_proof import detect_payment_proof


class TestPaymentProofDetection:
    """Test payment proof detection with various inputs."""

    def test_strong_keyword_always_proof(self):
        """Strong keywords (скрін, квитанцію) should always be proof."""
        assert detect_payment_proof("Надіслав скрін") is True
        assert detect_payment_proof("Ось квитанцію") is True
        assert detect_payment_proof("Доказ оплати") is True

    def test_weak_keyword_needs_image_or_url(self):
        """Weak keywords (оплатила, готово) need image/URL to be proof."""
        assert detect_payment_proof("Оплатила", has_image=True) is True
        assert detect_payment_proof("Оплатила", has_url=True) is True
        assert detect_payment_proof("Оплатила", has_image=False, has_url=False) is False

    def test_url_always_proof(self):
        """URL presence should always be proof."""
        assert detect_payment_proof("https://example.com/screenshot.jpg") is True
        assert detect_payment_proof("http://example.com/proof.png") is True
        assert detect_payment_proof("Ось посилання: https://example.com") is True

    def test_image_flag_always_proof(self):
        """Image flag should always be proof (even with empty text)."""
        assert detect_payment_proof("Оплатила", has_image=True) is True
        # Empty text with image → still proof (user sent screenshot)
        assert detect_payment_proof("", has_image=True) is True

    def test_russian_variant_скрин(self):
        """Russian variant 'скрин' should work."""
        assert detect_payment_proof("Надіслав скрин") is True

    def test_ukrainian_variant_скрін(self):
        """Ukrainian variant 'скрін' should work."""
        assert detect_payment_proof("Надіслав скрін") is True

    def test_partial_match_квитанц(self):
        """Partial match 'квитанц' should work."""
        assert detect_payment_proof("Ось квитанц") is True

    def test_empty_string(self):
        """Empty string should not be proof."""
        assert detect_payment_proof("") is False

    def test_no_keywords_no_image_no_url(self):
        """No keywords, no image, no URL → not proof."""
        assert detect_payment_proof("Дякую за замовлення") is False

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert detect_payment_proof("ОПЛАТИЛА", has_image=True) is True
        assert detect_payment_proof("Скрін") is True

