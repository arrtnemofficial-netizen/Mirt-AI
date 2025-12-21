"""
CRM Configuration Constants.
============================
Centralizes all external system strings to maintain 0% hardcoded strings in logic.
"""

from src.services.data.order_model import OrderStatus

# Snitkix CRM Status Mapping (External Titles)
SNITKIX_STATUS_TITLES = {
    OrderStatus.NEW: "Нові заявки",
    OrderStatus.PENDING_PAYMENT: "Виставлено рахунок",
    OrderStatus.PAID: "ОПЛАЧЕНО",
    OrderStatus.PROCESSING: "Оформлено замовлення",
    OrderStatus.SHIPPED: "shipped",
    OrderStatus.DELIVERED: "delivered",
    OrderStatus.CANCELLED: "cancelled",
    OrderStatus.RETURNED: "returned",
}

# Reverse mapping for webhook handling
REVERSE_SNITKIX_STATUS = {v: k for k, v in SNITKIX_STATUS_TITLES.items()}
