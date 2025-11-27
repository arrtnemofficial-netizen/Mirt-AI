"""
Tests for product adapter and validation.
"""
import pytest
from src.core.product_adapter import (
    ProductAdapter,
    ValidatedProduct,
    ProductValidationError,
)


class TestValidatedProduct:
    """Tests for ValidatedProduct model."""
    
    def test_create_valid_product(self):
        product = ValidatedProduct(
            id=1,
            name="Сукня Анна",
            size="110-116",
            color="рожевий",
            price=1200.0,
            photo_url="https://cdn.sitniks.com/photo.jpg",
        )
        assert product.id == 1
        assert product.price == 1200.0
    
    def test_invalid_price_zero(self):
        with pytest.raises(ValueError):
            ValidatedProduct(
                id=1,
                name="Test",
                price=0,
                photo_url="https://example.com/photo.jpg",
            )
    
    def test_invalid_price_negative(self):
        with pytest.raises(ValueError):
            ValidatedProduct(
                id=1,
                name="Test",
                price=-100,
                photo_url="https://example.com/photo.jpg",
            )
    
    def test_invalid_photo_url_http(self):
        with pytest.raises(ValueError):
            ValidatedProduct(
                id=1,
                name="Test",
                price=100,
                photo_url="http://example.com/photo.jpg",
            )
    
    def test_to_output_contract(self):
        product = ValidatedProduct(
            id=42,
            name="Test",
            price=500,
            photo_url="https://example.com/photo.jpg",
        )
        output = product.to_output_contract()
        assert output["id"] == 42
        assert "product_id" not in output


class TestProductAdapter:
    """Tests for ProductAdapter."""
    
    def test_from_supabase_with_id(self):
        row = {
            "id": 1,
            "name": "Сукня Анна",
            "price_uniform": True,
            "price_all_sizes": 1200,
            "sizes": ["110-116", "122-128"],
            "colors": {
                "рожевий": {"photo_url": "https://cdn.sitniks.com/pink.jpg"}
            },
        }
        product = ProductAdapter.from_supabase(row)
        assert product is not None
        assert product.id == 1
        assert product.price == 1200.0
    
    def test_from_supabase_with_product_id(self):
        """Test legacy format with product_id."""
        row = {
            "product_id": 2,
            "name": "Test",
            "price_uniform": True,
            "price_all_sizes": 500,
            "colors": {
                "білий": {"photo_url": "https://cdn.sitniks.com/white.jpg"}
            },
        }
        product = ProductAdapter.from_supabase(row)
        assert product is not None
        assert product.id == 2
    
    def test_from_dict_normalizes_id(self):
        data = {
            "product_id": 10,
            "name": "Test",
            "price": 100,
            "photo_url": "https://example.com/photo.jpg",
        }
        product = ProductAdapter.from_dict(data)
        assert product is not None
        assert product.id == 10
    
    def test_validate_for_send_valid(self):
        product = ValidatedProduct(
            id=1,
            name="Test",
            price=100,
            photo_url="https://cdn.sitniks.com/photo.jpg",
        )
        is_valid, errors = ProductAdapter.validate_for_send(product)
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_for_send_invalid_price(self):
        # Product with price=0 will fail to create, so test with missing id
        data = {"name": "Test", "price": 100, "photo_url": "https://example.com/photo.jpg"}
        is_valid, errors = ProductAdapter.validate_for_send(data)
        assert is_valid is False
        assert any("id" in e.field.lower() for e in errors)
    
    def test_validate_for_send_invalid_domain(self):
        product = ValidatedProduct(
            id=1,
            name="Test",
            price=100,
            photo_url="https://malicious.com/photo.jpg",
        )
        is_valid, errors = ProductAdapter.validate_for_send(product)
        assert is_valid is False
        assert any("domain" in e.message.lower() for e in errors)
    
    def test_batch_validate(self):
        products = [
            {"id": 1, "name": "Valid", "price": 100, "photo_url": "https://cdn.sitniks.com/1.jpg"},
            {"id": 2, "name": "Invalid", "price": 0, "photo_url": "https://cdn.sitniks.com/2.jpg"},
            {"id": 3, "name": "Valid2", "price": 200, "photo_url": "https://cdn.sitniks.com/3.jpg"},
        ]
        valid, errors = ProductAdapter.batch_validate(products)
        assert len(valid) == 2
        assert len(errors) > 0
    
    def test_allowed_domains(self):
        """Test that allowed domains are correctly defined."""
        assert "cdn.sitniks.com" in ProductAdapter.ALLOWED_PHOTO_DOMAINS
        assert "mirt.store" in ProductAdapter.ALLOWED_PHOTO_DOMAINS
