"""Compatibility shim for legacy import path."""

from src.services.conversation.client_data_parser_minimal import (
    extract_nova_poshta,
    extract_phone,
    parse_minimal,
)

__all__ = [
    "extract_nova_poshta",
    "extract_phone",
    "parse_minimal",
]
