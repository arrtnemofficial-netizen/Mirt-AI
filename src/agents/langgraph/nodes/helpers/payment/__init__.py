# helpers/payment/__init__.py
"""
Payment node helpers - modularized from payment.py.

This package contains extracted functions for cleaner architecture:
- utils: Price hydration, deps creation
- checkout: Initial checkout flow
- method_selection: Payment method handling
- delivery: Delivery data processing
- approval: HITL approval handling
- crm: CRM integration
"""

from .utils import ensure_prices_from_catalog
from .checkout import prepare_payment_and_interrupt
from .method_selection import handle_payment_method_selection
from .delivery import handle_delivery_data
from .approval import handle_approval_response
from .crm import persist_order_and_queue_crm

__all__ = [
    "ensure_prices_from_catalog",
    "prepare_payment_and_interrupt",
    "handle_payment_method_selection",
    "handle_delivery_data",
    "handle_approval_response",
    "persist_order_and_queue_crm",
]
