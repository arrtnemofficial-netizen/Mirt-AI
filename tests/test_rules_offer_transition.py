"""
Unit tests for offer_transition detection rules.
================================================
Tests detection of delivery request keywords.
"""

import pytest

from src.agents.langgraph.rules.offer_transition import detect_delivery_request


class TestOfferTransitionDetection:
    """Test delivery request detection."""

    def test_location_keywords(self):
        """Location keywords should trigger detection."""
        assert detect_delivery_request("Напишіть місто та відділення") is True
        assert detect_delivery_request("Вкажіть відділення Нової Пошти") is True
        assert detect_delivery_request("Нова пошта") is True

    def test_personal_data_keywords(self):
        """Personal data keywords should trigger detection."""
        assert detect_delivery_request("Вкажіть ПІБ та телефон") is True
        assert detect_delivery_request("Надішліть прізвище") is True
        assert detect_delivery_request("Номер телефону") is True

    def test_action_keywords(self):
        """Action keywords (requesting data) should trigger detection."""
        assert detect_delivery_request("Надішліть дані") is True
        assert detect_delivery_request("Напишіть адресу") is True
        assert detect_delivery_request("Вкажіть місто") is True

    def test_order_keywords(self):
        """Order keywords should trigger detection."""
        assert detect_delivery_request("Бронюємо замовлення") is True
        assert detect_delivery_request("Зарезервувати товар") is True
        assert detect_delivery_request("Оформити замовлення") is True

    def test_no_keywords(self):
        """No delivery keywords → no detection."""
        # Note: "замовлення" is in keywords, so this will match
        # Use text without any delivery-related words
        assert detect_delivery_request("Чудовий товар!") is False
        assert detect_delivery_request("Дякую!") is False
        assert detect_delivery_request("Скільки коштує?") is False

    def test_empty_string(self):
        """Empty string should not trigger detection."""
        assert detect_delivery_request("") is False

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert detect_delivery_request("МІСТО") is True
        assert detect_delivery_request("ПІБ") is True

    def test_partial_match(self):
        """Partial matches should work."""
        assert detect_delivery_request("Місто та відділення") is True
        assert detect_delivery_request("Нової Пошти відділення") is True

