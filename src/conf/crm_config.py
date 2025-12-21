"""
CRM Configuration Constants.
============================
Centralizes all external system strings to maintain 0% hardcoded strings in logic.
"""

from src.core.prompt_registry import load_yaml_from_registry
from src.core.registry_keys import SystemKeys
from src.services.data.order_model import OrderStatus

def _load_crm_titles() -> dict[str, str]:
    data = load_yaml_from_registry(SystemKeys.CRM_CONFIG.value)
    titles = data.get("snitkix_status_titles", {})
    if isinstance(titles, dict):
        return {str(k): str(v) for k, v in titles.items()}
    return {}


_SNITKIX_TITLES = _load_crm_titles()

# Snitkix CRM Status Mapping (External Titles)
SNITKIX_STATUS_TITLES = {
    OrderStatus.NEW: _SNITKIX_TITLES.get("new", "new"),
    OrderStatus.PENDING_PAYMENT: _SNITKIX_TITLES.get("pending_payment", "pending_payment"),
    OrderStatus.PAID: _SNITKIX_TITLES.get("paid", "paid"),
    OrderStatus.PROCESSING: _SNITKIX_TITLES.get("processing", "processing"),
    OrderStatus.SHIPPED: _SNITKIX_TITLES.get("shipped", "shipped"),
    OrderStatus.DELIVERED: _SNITKIX_TITLES.get("delivered", "delivered"),
    OrderStatus.CANCELLED: _SNITKIX_TITLES.get("cancelled", "cancelled"),
    OrderStatus.RETURNED: _SNITKIX_TITLES.get("returned", "returned"),
}

# Reverse mapping for webhook handling
REVERSE_SNITKIX_STATUS = {v: k for k, v in SNITKIX_STATUS_TITLES.items()}
