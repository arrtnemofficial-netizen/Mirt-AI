"""Tests for minimal client data parser.

The minimal parser handles ONLY phone and Nova Poshta numbers.
Names and cities are handled by LLM with proper prompting.
"""

from src.services.client_data_parser_minimal import (
    MinimalClientData,
    extract_nova_poshta,
    extract_phone,
    parse_minimal,
)


class TestPhoneExtraction:
    """Test phone number extraction."""

    def test_extract_phone_380_format(self):
        assert extract_phone("мій номер +380501234567") == "+380501234567"

    def test_extract_phone_0_format(self):
        assert extract_phone("телефон 0501234567") == "+380501234567"

    def test_extract_phone_with_spaces(self):
        assert extract_phone("050 123 45 67") == "+380501234567"

    def test_extract_phone_with_dashes(self):
        assert extract_phone("050-123-45-67") == "+380501234567"

    def test_extract_phone_none(self):
        assert extract_phone("немає телефону тут") is None


class TestNovaPoshtaExtraction:
    """Test Nova Poshta branch extraction."""

    def test_extract_np_short(self):
        assert extract_nova_poshta("нп 25") == "25"

    def test_extract_np_number_sign(self):
        assert extract_nova_poshta("НП №123") == "123"

    def test_extract_np_poshtamat(self):
        assert extract_nova_poshta("поштомат 456") == "456"

    def test_extract_np_viddilennya(self):
        assert extract_nova_poshta("відділення 25") == "25"

    def test_extract_np_nova_poshta_full(self):
        assert extract_nova_poshta("нова пошта 15") == "15"

    def test_extract_np_none(self):
        assert extract_nova_poshta("просто текст") is None


class TestParseMinimal:
    """Test minimal client data parsing."""

    def test_parse_phone_and_np(self):
        text = "+380501234567, нп 25"
        data = parse_minimal(text)

        assert data.phone == "+380501234567"
        assert data.nova_poshta == "25"

    def test_parse_only_phone(self):
        text = "телефон 0501234567"
        data = parse_minimal(text)

        assert data.phone == "+380501234567"
        assert data.nova_poshta is None

    def test_parse_only_np(self):
        text = "відділення 54"
        data = parse_minimal(text)

        assert data.phone is None
        assert data.nova_poshta == "54"

    def test_parse_nothing(self):
        text = "привіт, як справи?"
        data = parse_minimal(text)

        assert data.phone is None
        assert data.nova_poshta is None

    def test_parse_complex_message(self):
        """Test parsing real user message with all data."""
        text = "Немченко юрий волоимирович +380951392121 нп 54 киев"
        data = parse_minimal(text)

        # Minimal parser only extracts phone and NP
        # Name and city are handled by LLM
        assert data.phone == "+380951392121"
        assert data.nova_poshta == "54"
