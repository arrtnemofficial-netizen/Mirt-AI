# helpers/payment/crm.py
"""
CRM integration - Order persistence and CRM queue.
Extracted from payment.py for modularity.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.pydantic.deps import create_deps_from_state

from .utils import ensure_prices_from_catalog

logger = logging.getLogger(__name__)


async def persist_order_and_queue_crm(
    *,
    state: dict[str, Any],
    session_id: str,
    approval_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist order to database and queue for CRM if enabled."""
    crm_order_result = None
    try:
        deps = create_deps_from_state(state)

        # Construct order payload
        products = state.get("selected_products", [])
        products = await ensure_prices_from_catalog(products, session_id=session_id)
        order_items = []
        for p in products:
            order_items.append(
                {
                    "product_id": p.get("id"),
                    "name": p.get("name"),
                    "price": p.get("price"),
                    "size": p.get("size"),
                    "color": p.get("color"),
                    "quantity": 1,
                }
            )

        # Get sitniks_chat_id from state if available
        sitniks_chat_id = state.get("sitniks_chat_id") or state.get("metadata", {}).get("sitniks_chat_id")

        order_data = {
            "external_id": session_id,
            "source_id": deps.user_id,
            "user_nickname": deps.user_nickname,
            "sitniks_chat_id": sitniks_chat_id,  # For status updates in Sitniks
            "customer": {
                "full_name": deps.customer_name,
                "phone": deps.customer_phone,
                "city": deps.customer_city,
                "nova_poshta_branch": deps.customer_nova_poshta,
                "telegram_id": session_id if "telegram" in str(deps.user_id) else None,
                "manychat_id": session_id if "manychat" in str(deps.user_id) else None,
                "username": deps.user_nickname,
            },
            "items": order_items,
            "totals": {"total": approval_data.get("total_price", 0)},
            "status": "new",
            "delivery_method": "nova_poshta",
            "notes": "Created via Mirt-AI Agent",
            "source": "telegram" if "telegram" in str(deps.user_id) else "manychat",
        }

        # [USER-OVERRIDE] Disabled local order persistence
        # "НЕТ Я ЖЕ ОТКОЗАЛСЯ ОТ ОРДЕРС!! МИ ПРОСТО ОБНОВЛЯЕМ СТАТУСИ В СИТНИКС СРМ БЕЗ ОРДЕРОВ !!"
        if False:  # Force skip
            order_id = await deps.db.create_order(order_data)
            if order_id:
                logger.info("Order successfully saved to Supabase: ID %s", order_id)
            else:
                logger.error("Failed to save order to Supabase (returned None)")
        else:
            logger.info("Local order persistence SKIPPED (configured by user override)")
            order_id = "skipped"

        # =========================================================================
        # NOTE: Замовлення в PostgreSQL створюється завжди.
        # Sitniks CRM integration: ТІЛЬКИ статуси чатів (не створення замовлень).
        # =========================================================================
        crm_order_result = {"status": "skipped", "reason": "crm_orders_disabled_only_statuses_enabled"}

    except Exception as e:
        logger.exception("CRITICAL: Failed to save order to DB or queue CRM: %s", e)
        crm_order_result = {"status": "failed", "error": str(e)}

    return crm_order_result
