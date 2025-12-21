# 🤖 ManyChat Setup (Implementation Guide)

> **Version:** 5.0  
> **Source:** `src/integrations/manychat/pipeline.py`  
> **Updated:** 20 December 2025

---

## 🏗️ External Request Configuration (Exact Payload)

Based on `PipelineResult` dataclass in `pipeline.py`.

### 1. Request Body

Your ManyChat "External Request" **MUST** send this JSON body matching `process_manychat_pipeline` signature:

```json
{
  "user_id": "{{user_id}}",
  "text": "{{last_input_text}}",
  "image_url": "{{last_input_image_url}}",
  "extra_metadata": {
    "first_name": "{{first_name}}",
    "last_name": "{{last_name}}",
    "channel": "instagram",
    "has_image": "{{has_image_boolean}}" 
  }
}
```

> **Note:** `text` is required. If sending an image only, set `text` to something generic like "photo_sent".

### 2. Headers

Required for `X-ManyChat-Token` validation in `src/server/webhooks.py`:

| Header | Value |
|:-------|:------|
| `Content-Type` | `application/json` |
| `X-ManyChat-Token` | `your_verify_token_here` |

---

## ⚡ Pipeline Logic (`pipeline.py`)

Implementation details of `process_manychat_pipeline`:

1.  **Buffer:** Inputs are wrapped in `BufferedMessage`.
2.  **Debounce:** `debouncer.wait_for_debounce(user_id)` waits for 2s window.
3.  **Supersede:** If a new message arrives < 2s, the old one returns `None` (Superseded).
4.  **Time Budget:** `timeout=max(time_budget, 1.0)` enforces strict external timeout.
5.  **Result:** Returns `PipelineResult` containing the **aggregated** text.

### Push Mode Behavior
When `MANYCHAT_PUSH_MODE=true` is set:
- The API returns `200 OK {}` immediately (after debounce start).
- The actual processing happens in Celery task `src.workers.tasks.manychat.process_task`.
- Response is sent back via `client.send_content`.

---

## 🛡️ Troubleshooting

### "Message Lost"
Check logs for `manychat_debounce_superseded`. This means the user sent multiple messages rapidly, and only the LAST one was processed (normal behavior for debounce).

### "Response Timeout"
If `MANYCHAT_PUSH_MODE=false` (Legacy), the API creates a `ConversationHandler`. If this takes > 28s, ManyChat will timeout. **Always use Push Mode** for vision tasks.

---
