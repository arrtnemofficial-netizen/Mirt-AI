"""
Product Adapter - unification of product schemas.
================================================
Resolves id vs product_id issue:
- Internally uses `id` (as in OUTPUT_CONTRACT)
- Adapter converts from different formats

Usage:
    from src.core.product_adapter import ProductAdapter, ValidatedProduct
    
    # From Embedded Catalog or dict
    product = ProductAdapter.from_dict(row)
    
    # For OUTPUT_CONTRACT
    output_dict = product.to_output_contract()
    
    # Validate before sending
    validated = ProductAdapter.validate_for_send(product)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# VALIDATED PRODUCT MODEL (Pydantic)
# =============================================================================

class ValidatedProduct(BaseModel):
    """
    Product with strict validation.
    Uses `id` as the canonical field (matches OUTPUT_CONTRACT).
    """
    id: int = Field(..., gt=0, description="Product ID (must be positive)")
    name: str = Field(..., min_length=1)
    size: str = Field(default="")
    color: str = Field(default="")
    price: float = Field(..., gt=0, description="Price must be positive")
    photo_url: str = Field(..., min_length=1)
    sku: str | None = None
    category: str | None = None
    
    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        """Ensure photo_url is a valid HTTPS URL."""
        if not v:
            raise ValueError("photo_url cannot be empty")
        if not v.startswith("https://"):
            raise ValueError(f"photo_url must start with https://, got: {v[:50]}")
        return v
    
    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float) -> float:
        """Ensure price is positive."""
        if v <= 0:
            raise ValueError(f"price must be positive, got: {v}")
        return v
    
    def to_output_contract(self) -> dict[str, Any]:
        """Convert to OUTPUT_CONTRACT format (uses `id`)."""
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "color": self.color,
            "price": self.price,
            "photo_url": self.photo_url,
            "sku": self.sku,
            "category": self.category,
        }
    
    def to_legacy_format(self) -> dict[str, Any]:
        """Convert to legacy format (uses `product_id`)."""
        return {
            "product_id": self.id,
            "name": self.name,
            "size": self.size,
            "color": self.color,
            "price": self.price,
            "photo_url": self.photo_url,
            "sku": self.sku,
            "category": self.category,
        }


# =============================================================================
# PRODUCT ADAPTER
# =============================================================================

@dataclass
class ProductValidationError:
    """Error during product validation."""
    field: str
    message: str
    value: Any = None


class ProductAdapter:
    """
    Adapter for converting products between different formats.
    Single source of truth for product schema transformations.
    """
    
    # Allowed photo URL domains
    ALLOWED_PHOTO_DOMAINS = (
        "cdn.sitniks.com",
        "sitniks.com",
        "mirt.store",
        "cdn.mirt.store",
    )
    
    @classmethod
    def from_catalog_row(cls, row: dict[str, Any], color: str = "", size: str = "") -> ValidatedProduct | None:
        """Convert catalog row to ValidatedProduct."""
        if not row:
            return None

        # Strategy: try extraction helpers first (complex schema)
        price = cls._extract_price(row, size)
        photo_url = cls._extract_photo_url(row, color)
        sku = cls._extract_sku(row, color)
        
        # If extraction failed, fallback to direct keys (simple schema)
        if price is None:
            price = float(row.get("price", 0))
        if not photo_url:
            photo_url = row.get("photo_url", "")
            
        # Prepare data for common validation
        data = {
            "id": row.get("id") or row.get("product_id"),
            "name": row.get("name", ""),
            "size": size or cls._get_first_size(row) or row.get("size", ""),
            "color": color or cls._get_first_color(row) or row.get("color", ""),
            "price": price,
            "photo_url": photo_url,
            "sku": sku or row.get("sku"),
            "category": row.get("category"),
        }
        
        return cls._create_validated_product(data, source="catalog_row")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidatedProduct | None:
        """Convert any simple dict to ValidatedProduct."""
        if not data:
            return None
            
        # Normalize keys
        normalized = {
            "id": data.get("id") or data.get("product_id"),
            "name": data.get("name", ""),
            "size": data.get("size", ""),
            "color": data.get("color", ""),
            "price": float(data.get("price", 0)),
            "photo_url": data.get("photo_url", ""),
            "sku": data.get("sku"),
            "category": data.get("category"),
        }
        
        return cls._create_validated_product(normalized, source="dict")

    @classmethod
    def _create_validated_product(cls, data: dict[str, Any], source: str) -> ValidatedProduct | None:
        """Internal helper to create and validate product from normalized dict."""
        product_id = data.get("id")
        if not product_id:
            return None
            
        try:
            return ValidatedProduct(
                id=int(product_id),
                name=data["name"],
                size=data["size"],
                color=data["color"],
                price=data["price"],
                photo_url=data["photo_url"],
                sku=data["sku"],
                category=data["category"],
            )
        except Exception as e:
            # Only log warnings for critical data missing, debug for minor issues
            if data["price"] <= 0:
                logger.warning("Invalid price for product %s: %s", product_id, data["price"])
            elif not data["photo_url"]:
                logger.warning("Missing photo_url for product %s", product_id)
            else:
                logger.debug("Failed to create ValidatedProduct from %s: %s", source, e)
            return None
    
    @classmethod
    def validate_for_send(cls, product: Union[ValidatedProduct, dict[str, Any]]) -> tuple[bool, list[ProductValidationError]]:
        """
        Validate product before sending to channel.
        Returns (is_valid, list_of_errors).
        """
        errors: list[ProductValidationError] = []
        
        if isinstance(product, dict):
            product_obj = cls.from_dict(product)
            if product_obj is None:
                errors.append(ProductValidationError("id", "Missing or invalid product ID"))
                return False, errors
        else:
            product_obj = product
        
        # Check ID
        if not product_obj.id or product_obj.id <= 0:
            errors.append(ProductValidationError("id", "ID must be positive", product_obj.id))
        
        # Check price
        if product_obj.price <= 0:
            errors.append(ProductValidationError("price", "Price must be positive", product_obj.price))
        
        # Check photo_url
        if not product_obj.photo_url:
            errors.append(ProductValidationError("photo_url", "Photo URL is required"))
        elif not product_obj.photo_url.startswith("https://"):
            errors.append(ProductValidationError("photo_url", "Must start with https://", product_obj.photo_url))
        else:
            # Check domain
            domain_ok = any(d in product_obj.photo_url for d in cls.ALLOWED_PHOTO_DOMAINS)
            if not domain_ok:
                errors.append(ProductValidationError(
                    "photo_url", 
                    f"Domain not in allowed list: {cls.ALLOWED_PHOTO_DOMAINS}",
                    product_obj.photo_url
                ))
        
        # Check name
        if not product_obj.name:
            errors.append(ProductValidationError("name", "Name is required"))
        
        return len(errors) == 0, errors
    
    @classmethod
    def batch_validate(cls, products: list[Union[ValidatedProduct, dict[str, Any]]]) -> tuple[list[ValidatedProduct], list[ProductValidationError]]:
        """
        Validate and filter a batch of products.
        Returns (valid_products, all_errors).
        """
        valid_products: list[ValidatedProduct] = []
        all_errors: list[ProductValidationError] = []
        
        for i, p in enumerate(products):
            is_valid, errors = cls.validate_for_send(p)
            if is_valid:
                if isinstance(p, ValidatedProduct):
                    valid_products.append(p)
                else:
                    validated = cls.from_dict(p)
                    if validated:
                        valid_products.append(validated)
            else:
                for e in errors:
                    e.field = f"products[{i}].{e.field}"
                all_errors.extend(errors)
        
        return valid_products, all_errors
    
    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------
    
    @classmethod
    def _extract_price(cls, row: dict[str, Any], size: str = "") -> float | None:
        """Extract price from catalog row."""
        # Check price_uniform
        if row.get("price_uniform") and row.get("price_all_sizes"):
            return float(row["price_all_sizes"])
        
        # Check price_by_size
        price_by_size = row.get("price_by_size")
        if price_by_size and isinstance(price_by_size, dict):
            if size and size in price_by_size:
                return float(price_by_size[size])
            # Return first available price
            for v in price_by_size.values():
                return float(v)
        
        # Fallback to direct price field
        if row.get("price"):
            return float(row["price"])
        
        return None
    
    @classmethod
    def _extract_photo_url(cls, row: dict[str, Any], color: str = "") -> str | None:
        """Extract photo_url from catalog row."""
        # Direct photo_url field
        if row.get("photo_url"):
            return row["photo_url"]
        
        # Extract from colors jsonb
        colors = row.get("colors")
        if colors and isinstance(colors, dict):
            if color and color in colors:
                color_data = colors[color]
                if isinstance(color_data, dict) and color_data.get("photo_url"):
                    return color_data["photo_url"]
            # Return first available photo_url
            for color_data in colors.values():
                if isinstance(color_data, dict) and color_data.get("photo_url"):
                    return color_data["photo_url"]
        
        return None
    
    @classmethod
    def _extract_sku(cls, row: dict[str, Any], color: str = "") -> str | None:
        """Extract SKU from catalog row."""
        colors = row.get("colors")
        if colors and isinstance(colors, dict):
            if color and color in colors:
                color_data = colors[color]
                if isinstance(color_data, dict):
                    return color_data.get("sku")
            # Return first available SKU
            for color_data in colors.values():
                if isinstance(color_data, dict) and color_data.get("sku"):
                    return color_data["sku"]
        return row.get("sku")
    
    @classmethod
    def _get_first_size(cls, row: dict[str, Any]) -> str:
        """Get first available size from row."""
        sizes = row.get("sizes")
        if sizes and isinstance(sizes, list) and len(sizes) > 0:
            return str(sizes[0])
        return ""
    
    @classmethod
    def _get_first_color(cls, row: dict[str, Any]) -> str:
        """Get first available color from row."""
        colors = row.get("colors")
        if colors and isinstance(colors, dict):
            return next(iter(colors.keys()), "")
        return row.get("color_variant", "")
