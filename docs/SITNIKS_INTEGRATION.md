# 🔗 Sitniks CRM Integration (Implementation)

> **Version:** 5.0 (Implementation)  
> **Source:** `src/integrations/crm/snitkix.py`  
> **Updated:** 20 December 2025

---

## 🏗️ Technical Implementation

The integration is implemented via `SnitkixCRMClient` class which handles authentication (`Bearer token`) and payload mapping.

### Status Mapping (`STATUS_MAPPING`)

Exact mapping from our `OrderStatus` enum to Sitniks string values:

| Internal Status | Snitkix Value |
|:----------------|:--------------|
| `NEW` | `"Нові заявки"` |
| `PENDING_PAYMENT` | `"Виставлено рахунок"` |
| `PAID` | `"ОПЛАЧЕНО"` |
| `PROCESSING` | `"Оформлено замовлення"` |

---

## 📦 Order Payload (`create_order`)

The `_build_order_payload` method generates this exact structure required by `/api/orders`:

```json
{
  "external_id": "session_uuid",
  "source": "telegram",
  "customer": {
    "name": "User Name",
    "phone": "+380...",
    "email": "optional"
  },
  "delivery": {
    "method": "nova_poshta",
    "city": "Kyiv",
    "address": "Branch #1"
  },
  "items": [
    {
      "product_id": "123",
      "sku": "DRESS-RED-116",
      "price": 1200,
      "quantity": 1
    }
  ],
  "payment_method": "mono",
  "status": "Нові заявки"
}
```

---

## 🛡️ Resilience & Error Handling

Implemented in `SnitkixCRMClient._handle_error`:

1. **Authentication Error (401):**
   - Returns `CRMResponse.fail(type=AUTHENTICATION)`.
   - **Action:** Check `SNITKIX_API_KEY`.

2. **Validation Error (422):**
   - Typically invalid phone format or missing SKU.
   - **Action:** Graph catches this via `crm_error_node` and asks user to retry.

3. **Connection Error (Timeout/500):**
   - Retried by Celery task `src.workers.tasks.crm.sync_order`.
   - Max 3 retries with exponential backoff.

---

## 🔌 API Client Singleton

The client is managed as a singleton to reuse the `httpx.AsyncClient` connection pool:

```python
def get_snitkix_client() -> SnitkixCRMClient:
    global _crm_client
    if _crm_client is None:
        _crm_client = SnitkixCRMClient()
    return _crm_client
```

---
