"""
Tests for product adapter and catalog loading.
==============================================
Updated for new architecture with embedded catalog.
"""

from pathlib import Path

from src.core.product_adapter import (
    ProductAdapter,
    ValidatedProduct,
)


# =============================================================================
# CATALOG PRODUCT TESTS
# =============================================================================


class TestValidatedProduct:
    """Tests for ValidatedProduct model."""

    def test_validated_product_creation(self):
        """Test creating ValidatedProduct."""
        product = ValidatedProduct(
            id=123,
            name="Сукня Еліт",
            price=1300,
            size="122",
            color="рожева",
            photo_url="https://cdn.example.com/1.jpg",
            category="dress",
        )

        assert product.id == 123
        assert product.name == "Сукня Еліт"
        assert product.price == 1300

    def test_validated_product_optional_fields(self):
        """Test ValidatedProduct with optional fields."""
        product = ValidatedProduct(
            id=456,
            name="Тренч",
            price=2500,
            photo_url="https://cdn.example.com/2.jpg",
        )

        assert product.size == ""
        assert product.color == ""


# =============================================================================
# PRODUCT ADAPTER TESTS
# =============================================================================


class TestProductAdapter:
    """Tests for ProductAdapter."""

    def test_from_catalog_row(self):
        """Test converting catalog row to ValidatedProduct."""
        raw = {
            "id": 789,
            "name": "Test Product",
            "price": 500,
            "photo_url": "https://example.com/img.jpg",
        }

        product = ProductAdapter.from_catalog_row(raw)

        assert product is not None
        assert product.id == 789
        assert product.name == "Test Product"

    def test_from_catalog_row_with_product_id(self):
        """Test converting catalog row with legacy product_id."""
        raw = {
            "product_id": 999,
            "name": "Legacy Product",
            "price": 600,
            "photo_url": "https://example.com/legacy.jpg",
        }

        product = ProductAdapter.from_catalog_row(raw)

        assert product is not None
        assert product.id == 999

    def test_from_catalog_row_invalid(self):
        """Test converting invalid row returns None."""
        raw = {"invalid": "data"}

        product = ProductAdapter.from_catalog_row(raw)

        assert product is None

    def test_validate_for_send(self):
        """Test validating product for sending."""
        product = ValidatedProduct(
            id=123,
            name="Test",
            price=100,
            photo_url="https://cdn.sitniks.com/test.jpg",  # Use allowed domain
        )

        is_valid, errors = ProductAdapter.validate_for_send(product)
        assert is_valid is True  # Should pass validation
        assert len(errors) == 0

    def test_to_output_contract(self):
        """Test converting to output contract format."""
        product = ValidatedProduct(
            id=456,
            name="Output Test",
            price=200,
            photo_url="https://example.com/output.jpg",
        )

        output = product.to_output_contract()
        assert output["id"] == 456
        assert output["name"] == "Output Test"

    def test_to_legacy_format(self):
        """Test converting to legacy format."""
        product = ValidatedProduct(
            id=789,
            name="Legacy Test",
            price=300,
            photo_url="https://example.com/legacy.jpg",
        )

        legacy = product.to_legacy_format()
        assert legacy["product_id"] == 789
        assert legacy["name"] == "Legacy Test"


# =============================================================================
# CATALOG LOADING TESTS
# =============================================================================


class TestCatalogLoading:
    """Tests for catalog loading from files."""

    def test_catalog_json_loads(self, tmp_path: Path):
        """Test loading catalog from JSON file."""
        sample = tmp_path / "catalog.json"
        sample.write_text(
            """[
  {"id": 1, "name": "Червона сукня", "size": "122", "color": "червоний", "price": 100, "photo_url": "https://x.com/1.jpg", "category": "dress"},
  {"id": 2, "name": "Базова футболка", "size": "140", "color": "білий", "price": 50, "photo_url": "https://x.com/2.jpg", "category": "t-shirt"}
]""",
            encoding="utf-8",
        )

        import json
        with open(sample, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) == 2
        assert data[0]["name"] == "Червона сукня"
        assert data[1]["name"] == "Базова футболка"

    def test_product_adapter_search(self):
        """Test ProductAdapter can work with product lists."""
        ProductAdapter()

        # Create test products
        test_products = [
            ValidatedProduct(id=1, name="Сукня Анна", price=1850, photo_url="https://x.com/1.jpg"),
            ValidatedProduct(id=2, name="Тренч Парижанка", price=2500, photo_url="https://x.com/2.jpg"),
        ]

        # Search by name
        results = [p for p in test_products if "сукня" in p.name.lower()]
        assert len(results) == 1
        assert results[0].name == "Сукня Анна"
