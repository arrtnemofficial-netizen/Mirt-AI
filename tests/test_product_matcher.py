"""
Product Matcher Tests
=====================

Тести для сервісу нормалізації назв продуктів.
Перевіряє що всі варіації імен правильно нормалізуються.
"""

import pytest

from src.services.catalog import (
    extract_color_from_name,
    is_valid_product_name,
    normalize_product_name,
    parse_product_response,
    reload_canonical_names,
)


class TestNormalizeProductName:
    """Tests for normalize_product_name function."""

    def setup_method(self):
        """Reload canonical names before each test."""
        reload_canonical_names()

    # =========================================================================
    # ПОВНІ НАЗВИ
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Костюм Лагуна", "Костюм Лагуна"),
            ("Костюм Мрія", "Костюм Мрія"),
            ("Костюм Ритм", "Костюм Ритм"),
            ("Костюм Каприз", "Костюм Каприз"),
            ("Костюм Валері", "Костюм Валері"),
            ("Костюм Мерея", "Костюм Мерея"),
            ("Сукня Анна", "Сукня Анна"),
            ("Тренч екошкіра", "Тренч екошкіра"),
            ("Тренч", "Тренч"),
        ],
    )
    def test_full_names(self, input_name, expected):
        """Full canonical names should match exactly."""
        assert normalize_product_name(input_name) == expected

    # =========================================================================
    # КОРОТКІ НАЗВИ (без "Костюм"/"Сукня")
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("лагуна", "Костюм Лагуна"),
            ("мрія", "Костюм Мрія"),
            ("ритм", "Костюм Ритм"),
            ("каприз", "Костюм Каприз"),
            ("валері", "Костюм Валері"),
            ("мерея", "Костюм Мерея"),
            ("анна", "Сукня Анна"),
        ],
    )
    def test_short_names(self, input_name, expected):
        """Short names without prefix should match."""
        assert normalize_product_name(input_name) == expected

    # =========================================================================
    # РЕГІСТР (lower/upper/mixed)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("КОСТЮМ ЛАГУНА", "Костюм Лагуна"),
            ("костюм лагуна", "Костюм Лагуна"),
            ("Костюм лагуна", "Костюм Лагуна"),
            ("ЛАГУНА", "Костюм Лагуна"),
            ("Лагуна", "Костюм Лагуна"),
            ("МРІЯ", "Костюм Мрія"),
        ],
    )
    def test_case_insensitive(self, input_name, expected):
        """Names should be case-insensitive."""
        assert normalize_product_name(input_name) == expected

    # =========================================================================
    # НАЗВИ З КОЛЬОРОМ (LLM часто додає колір)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Костюм Лагуна рожевий", "Костюм Лагуна"),
            ("Костюм Мрія жовтий", "Костюм Мрія"),
            ("лагуна рожевий", "Костюм Лагуна"),
            ("мрія помаранчевий", "Костюм Мрія"),
            ("Ритм шоколадний", "Костюм Ритм"),
            ("Ритм коричневий", "Костюм Ритм"),
            ("Каприз бордовий", "Костюм Каприз"),
            ("Сукня Анна голубий", "Сукня Анна"),
            ("анна малина", "Сукня Анна"),
        ],
    )
    def test_names_with_color(self, input_name, expected):
        """Names with color suffix should still match base product."""
        assert normalize_product_name(input_name) == expected

    # =========================================================================
    # ТРЕНЧІ (два типи)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Тренч екошкіра", "Тренч екошкіра"),
            ("тренч еко", "Тренч екошкіра"),
            ("тренч шкіра", "Тренч екошкіра"),
            ("Тренч", "Тренч"),
            ("тренч тканинний", "Тренч"),
        ],
    )
    def test_trench_variations(self, input_name, expected):
        """Trench variations should match correctly."""
        assert normalize_product_name(input_name) == expected

    # =========================================================================
    # НЕВАЛІДНІ НАЗВИ
    # =========================================================================

    @pytest.mark.parametrize(
        "input_name",
        [
            "",
            "   ",
            "Костюм Неіснуючий",
            "Випадкова назва",
            "Nike костюм",
        ],
    )
    def test_invalid_names(self, input_name):
        """Invalid names should return None."""
        assert normalize_product_name(input_name) is None


class TestExtractColor:
    """Tests for extract_color_from_name function."""

    @pytest.mark.parametrize(
        "input_name,expected_color",
        [
            ("Костюм Лагуна рожевий", "рожевий"),
            ("лагуна жовтий", "жовтий"),
            ("Мрія помаранчевий", "помаранчевий"),
            ("Сукня Анна голубий", "голубий"),
            ("Тренч екошкіра капучіно", "капучіно"),
            ("Костюм Ритм бордовий", "бордовий"),
            ("Тренч темно синій", "темно синій"),
        ],
    )
    def test_extract_known_colors(self, input_name, expected_color):
        """Should extract known colors from product names."""
        assert extract_color_from_name(input_name) == expected_color

    @pytest.mark.parametrize(
        "input_name",
        [
            "Костюм Лагуна",
            "Мрія",
            "Тренч екошкіра",
        ],
    )
    def test_no_color(self, input_name):
        """Should return None when no color present."""
        assert extract_color_from_name(input_name) is None


class TestParseProductResponse:
    """Tests for parse_product_response function."""

    def setup_method(self):
        reload_canonical_names()

    def test_full_parse(self):
        """Should parse full product name with color."""
        result = parse_product_response("Костюм Лагуна рожевий")
        assert result["name"] == "Костюм Лагуна"
        assert result["color"] == "рожевий"
        assert result["valid"] is True

    def test_partial_parse(self):
        """Should parse product name without color."""
        result = parse_product_response("Мрія")
        assert result["name"] == "Костюм Мрія"
        assert result["color"] is None
        assert result["valid"] is True

    def test_invalid_parse(self):
        """Should handle invalid product names."""
        result = parse_product_response("Невідомий товар")
        assert result["name"] is None
        assert result["valid"] is False


class TestIsValidProductName:
    """Tests for is_valid_product_name function."""

    def setup_method(self):
        reload_canonical_names()

    @pytest.mark.parametrize(
        "name",
        [
            "Костюм Лагуна",
            "Костюм Мрія",
            "Костюм Ритм",
            "Костюм Каприз",
            "Костюм Валері",
            "Костюм Мерея",
            "Сукня Анна",
            "Тренч екошкіра",
            "Тренч",
        ],
    )
    def test_valid_names(self, name):
        """Should return True for valid canonical names."""
        assert is_valid_product_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "лагуна",  # Not canonical (short form)
            "Костюм",
            "Невідомий",
            "",
        ],
    )
    def test_invalid_names(self, name):
        """Should return False for non-canonical names."""
        assert is_valid_product_name(name) is False
