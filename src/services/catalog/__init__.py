from .catalog_service import CatalogService
from .product_matcher import (
    extract_color_from_name,
    extract_requested_color,
    is_valid_product_name,
    normalize_product_name,
    parse_product_response,
    reload_canonical_names,
)

__all__ = [
    "CatalogService",
    "extract_color_from_name",
    "extract_requested_color",
    "is_valid_product_name",
    "normalize_product_name",
    "parse_product_response",
    "reload_canonical_names",
]
