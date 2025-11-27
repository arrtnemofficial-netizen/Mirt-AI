"""Tests for client data parser."""
import pytest

from src.services.client_data_parser import (
    parse_client_data,
    extract_phone,
    extract_city,
    extract_nova_poshta,
    extract_full_name,
    normalize_phone,
    ClientData,
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


class TestCityExtraction:
    """Test city extraction."""

    def test_extract_city_kyiv(self):
        # Direct city name mention
        result = extract_city("Київ, відділення 25")
        assert result is not None
        assert "київ" in result.lower()
    
    def test_extract_city_kharkiv(self):
        result = extract_city("м. Харків")
        assert result is not None
        assert "харків" in result.lower()
    
    def test_extract_city_lviv(self):
        result = extract_city("Львів, відділення 25")
        assert result is not None
        assert "львів" in result.lower()
    
    def test_extract_city_none(self):
        assert extract_city("просто текст") is None


class TestNovaPoshtaExtraction:
    """Test Nova Poshta branch extraction."""

    def test_extract_np_viddilennya(self):
        assert extract_nova_poshta("відділення 25") == "25"
    
    def test_extract_np_number_sign(self):
        assert extract_nova_poshta("НП №123") == "123"
    
    def test_extract_np_poshtamat(self):
        assert extract_nova_poshta("поштомат 456") == "456"
    
    def test_extract_np_none(self):
        assert extract_nova_poshta("просто текст") is None


class TestFullNameExtraction:
    """Test full name extraction."""

    def test_extract_name_three_words(self):
        # Three words is more reliable for detection
        result = extract_full_name("Петренко Петро Петрович")
        assert result is not None
        assert "Петренко" in result
    
    def test_extract_name_with_context(self):
        # Name with surrounding context
        result = extract_full_name("Отримувач: Коваленко Олена Миколаївна, телефон")
        assert result is not None
        assert "Коваленко" in result
    
    def test_extract_name_with_phone(self):
        result = extract_full_name("Шевченко Тарас Григорович 0501234567")
        assert result is not None
        assert "Шевченко" in result
        assert "0501234567" not in (result or "")


class TestParseClientData:
    """Test full client data parsing."""

    def test_parse_complete_data(self):
        text = "Іванов Іван Іванович, 0501234567, Київ, відділення 25"
        data = parse_client_data(text)
        
        assert data.phone == "+380501234567"
        assert data.city is not None
        assert "київ" in data.city.lower()
        assert data.nova_poshta == "25"
    
    def test_parse_partial_data(self):
        text = "телефон 0501234567"
        data = parse_client_data(text)
        
        assert data.phone == "+380501234567"
        assert data.city is None
        assert data.nova_poshta is None
    
    def test_is_complete(self):
        complete = ClientData(
            full_name="Іванов Іван",
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
        )
        assert complete.is_complete() is True
        
        incomplete = ClientData(phone="+380501234567")
        assert incomplete.is_complete() is False
    
    def test_to_dict(self):
        data = ClientData(
            full_name="Іванов Іван",
            phone="+380501234567",
            city="Київ",
            nova_poshta="25",
        )
        d = data.to_dict()
        
        assert d["client_name"] == "Іванов Іван"
        assert d["client_phone"] == "+380501234567"
        assert d["client_city"] == "Київ"
        assert d["client_nova_poshta"] == "25"


class TestNormalizePhone:
    """Test phone normalization."""

    def test_normalize_380(self):
        assert normalize_phone("380501234567") == "+380501234567"
    
    def test_normalize_0(self):
        assert normalize_phone("0501234567") == "+380501234567"
    
    def test_normalize_with_plus(self):
        assert normalize_phone("+380501234567") == "+380501234567"
