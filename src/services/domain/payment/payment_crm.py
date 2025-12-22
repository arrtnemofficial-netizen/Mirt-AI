"""
Payment CRM Service.
====================
Handles order persistence in DB and submission to CRM via queue/service.
"""

from __future__ import annotations

import logging
import hashlib
from typing import Any

from src.services.data.catalog_service import CatalogService
from src.integrations.crm.crmservice import get_crm_service
from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
from src.conf.config import settings

logger = logging.getLogger(__name__)


async def hydrate_prices(products: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """Ensure all products have prices from catalog."""
    if not products:
        return products

    catalog = CatalogService()
    updated = []

    for p in products:
        try:
            price = p.get("price", 0)
            if isinstance(price, (int, float)) and price > 0:
                updated.append(p)
                continue

            name = str(p.get("name") or "").strip()
            size = p.get("size")
            if not name:
                updated.append(p)
                continue

            results = await catalog.search_products(query=name, limit=1)
            db_product = results[0] if results else {}

            if db_product:
                db_price = CatalogService.get_price_for_size(db_product, size)
                if db_price and db_price > 0:
                    p = {**p, "price": db_price}
        except Exception as e:
            logger.debug("[SESSION %s] Price hydration failed for %s: %s", session_id, p.get("name"), e)

        updated.append(p)

    return updated


async def create_and_submit_order(
    *,
    session_id: str,
    user_id: str,
    user_nickname: str | None,
    metadata: dict[str, Any],
    products: list[dict[str, Any]],
    total_price: float,
) -> dict[str, Any]:
    """
    Persist order in Supabase and submit to Snitkix CRM.
    """
    try:
        # Prepare order items
        order_items = []
        for p in products:
            order_items.append({
                "product_id": p.get("id"),
                "name": p.get("name"),
                "price": p.get("price"),
                "size": p.get("size"),
                "color": p.get("color"),
                "quantity": 1,
            })

        order_data = {
            "external_id": session_id,
            "source_id": user_id,
            "user_nickname": user_nickname,
            "customer": {
                "full_name": metadata.get("customer_name"),
                "phone": metadata.get("customer_phone"),
                "city": metadata.get("customer_city"),
                "nova_poshta_branch": metadata.get("customer_nova_poshta"),
                "telegram_id": session_id if "telegram" in str(user_id) else None,
                "manychat_id": session_id if "manychat" in str(user_id) else None,
                "username": user_nickname,
            },
            "items": order_items,
            "totals": {"total": total_price},
            "status": "new",
            "delivery_method": "nova_poshta",
            "notes": "Created via Mirt-AI Agent",
            "source": "telegram" if "telegram" in str(user_id) else "manychat",
        }

        # 0. Ledger Idempotency Check
        vision_result_id = metadata.get("vision_result_id")
        if vision_result_id:
            from src.services.domain.vision.vision_ledger import get_vision_ledger
            ledger = get_vision_ledger()
            # We don't have a direct 'get_by_id' in current VisionLedger, 
            # but we can assume if it's in metadata and we want strictly 
            # one order per vision_result, we should check existing orders.
            # However, standard practice is to use the ledger to block duplicates.
            # If vision_result_id exists and we already have an order for it, block.
            from src.services.infra.supabase_client import get_supabase_client
            supabase = get_supabase_client()
            if supabase:
                existing_order = supabase.table("crm_orders").select("id").eq("metadata->>vision_result_id", vision_result_id).execute()
                if existing_order.data:
                    logger.info("[SESSION %s] Order already exists for vision_result_id %s, skipping", session_id, vision_result_id)
                    return {"status": "success", "message": "Duplicate blocked via vision_result_id", "order_id": existing_order.data[0]["id"]}
        supabase = get_supabase_client()
        if supabase:
            try:
                supabase.table("crm_orders").insert(order_data).execute()
                logger.info("[SESSION %s] Order saved to Supabase", session_id)
            except Exception as e:
                logger.error("[SESSION %s] Supabase insert failed: %s", session_id, e)

        # 2. CRM Submission
        # Idempotency
        products_str = "|".join(sorted(p.get("name", "") for p in products))
        idempotency_data = f"{session_id}|{products_str}|{int(total_price * 100)}"
        idempotency_hash = hashlib.sha256(idempotency_data.encode()).hexdigest()[:16]
        external_id = f"{session_id}_{idempotency_hash}"

        crm_service = get_crm_service()
        result = await crm_service.create_order_with_persistence(
            session_id=session_id,
            order_data=order_data,
            external_id=external_id,
        )

        # 3. Status Update
        if settings.ENABLE_CRM_INTEGRATION:
            try:
                sitniks_chat = get_sitniks_chat_service()
                if sitniks_chat.enabled:
                    # Depending on flow, we might set different status
                    pass
            except Exception as e:
                logger.warning("[SESSION %s] Status update failed: %s", session_id, e)

        return result

    except Exception as e:
        logger.exception("[SESSION %s] Order submission failed: %s", session_id, e)
        return {"status": "failed", "error": str(e)}
