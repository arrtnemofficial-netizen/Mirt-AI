"""
Tests for Product Deduplication Utilities.
==========================================
Professional-grade tests for product comparison and deduplication.
"""

import pytest

from src.agents.langgraph.nodes.helpers.vision.product_deduplication import (
    add_product_safely,
    is_product_duplicate,
    normalize_product_key,
)


class TestNormalizeProductKey:
    """Tests for product key normalization."""

    def test_normalize_basic_product(self):
        """Test normalization of basic product."""
        product = {"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}
        key = normalize_product_key(product)
        assert key == "костюм лагуна|рожевий|110"

    def test_normalize_with_whitespace(self):
        """Test normalization handles whitespace correctly."""
        product = {"name": "Костюм  Лагуна  ", "color": "  РОЖЕВИЙ  ", "size": "110"}
        key = normalize_product_key(product)
        assert key == "костюм лагуна|рожевий|110"

    def test_normalize_missing_fields(self):
        """Test normalization with missing fields."""
        product = {"name": "Костюм Лагуна"}
        key = normalize_product_key(product)
        assert key == "костюм лагуна||"

    def test_normalize_empty_product(self):
        """Test normalization of empty product."""
        product = {}
        key = normalize_product_key(product)
        assert key == "||"

    def test_normalize_case_insensitive(self):
        """Test normalization is case-insensitive."""
        product1 = {"name": "Костюм Лагуна", "color": "Рожевий"}
        product2 = {"name": "КОСТЮМ ЛАГУНА", "color": "РОЖЕВИЙ"}
        key1 = normalize_product_key(product1)
        key2 = normalize_product_key(product2)
        assert key1 == key2


class TestIsProductDuplicate:
    """Tests for duplicate detection."""

    def test_exact_duplicate_strict(self):
        """Test exact duplicate detection (strict mode)."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        new = {"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}
        assert is_product_duplicate(new, existing, strict=True) is True

    def test_different_size_strict(self):
        """Test different size is not duplicate in strict mode."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        new = {"name": "Костюм Лагуна", "color": "рожевий", "size": "116"}
        assert is_product_duplicate(new, existing, strict=True) is False

    def test_same_name_color_fuzzy(self):
        """Test same name+color is duplicate in fuzzy mode."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        new = {"name": "Костюм Лагуна", "color": "рожевий", "size": "116"}
        assert is_product_duplicate(new, existing, strict=False) is True

    def test_different_color_not_duplicate(self):
        """Test different color is not duplicate."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        new = {"name": "Костюм Лагуна", "color": "жовтий", "size": "110"}
        assert is_product_duplicate(new, existing, strict=False) is False

    def test_empty_existing_list(self):
        """Test empty existing list returns False."""
        existing = []
        new = {"name": "Костюм Лагуна", "color": "рожевий"}
        assert is_product_duplicate(new, existing) is False

    def test_whitespace_normalization(self):
        """Test whitespace normalization in duplicate check."""
        existing = [{"name": "Костюм  Лагуна", "color": "  рожевий  "}]
        new = {"name": "Костюм Лагуна", "color": "рожевий"}
        assert is_product_duplicate(new, existing, strict=True) is True


class TestAddProductSafely:
    """Tests for safe product addition."""

    def test_add_to_empty_list(self):
        """Test adding product to empty list."""
        existing = []
        new = {"name": "Костюм Лагуна", "color": "рожевий"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 1
        assert was_added is True
        assert products[0] == new

    def test_add_non_duplicate(self):
        """Test adding non-duplicate product."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий"}]
        new = {"name": "Костюм Мрія", "color": "жовтий"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 2
        assert was_added is True

    def test_skip_duplicate(self):
        """Test skipping duplicate product."""
        existing = [{"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}]
        new = {"name": "Костюм Лагуна", "color": "рожевий", "size": "110"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 1
        assert was_added is False

    def test_empty_product_validation(self):
        """Test validation rejects empty product."""
        existing = [{"name": "Костюм Лагуна"}]
        new = {}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 1  # Existing unchanged
        assert was_added is False

    def test_product_without_name_validation(self):
        """Test validation rejects product without name."""
        existing = [{"name": "Костюм Лагуна"}]
        new = {"color": "рожевий"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 1  # Existing unchanged
        assert was_added is False

    def test_does_not_mutate_existing(self):
        """Test that existing list is not mutated."""
        existing = [{"name": "Костюм Лагуна"}]
        new = {"name": "Костюм Мрія"}
        products, _ = add_product_safely(new, existing)
        assert len(existing) == 1  # Original unchanged
        assert len(products) == 2  # New list has both

    def test_multiple_products(self):
        """Test adding to list with multiple products."""
        existing = [
            {"name": "Костюм Лагуна", "color": "рожевий"},
            {"name": "Костюм Мрія", "color": "жовтий"},
        ]
        new = {"name": "Сукня Анна", "color": "білий"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 3
        assert was_added is True

    def test_duplicate_in_multiple_products(self):
        """Test duplicate detection in list with multiple products."""
        existing = [
            {"name": "Костюм Лагуна", "color": "рожевий"},
            {"name": "Костюм Мрія", "color": "жовтий"},
        ]
        new = {"name": "Костюм Лагуна", "color": "рожевий"}
        products, was_added = add_product_safely(new, existing)
        assert len(products) == 2  # Duplicate not added
        assert was_added is False

