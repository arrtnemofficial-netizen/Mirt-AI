# Celery & Background Tasks

## Overview

MIRT AI uses Celery for tasks that shouldn't block the main request loop, such as:
- Logging messages to Supabase.
- Sending proactive follow-ups.
- Syncing orders to CRM.

## Architecture

- **Broker**: Redis
- **Backend**: Redis
- **Worker**: `src/workers/celery_app.py`

## 🚦 Tasks

### 1. `process_message`
- **Queue**: `messages`
- **Trigger**: After every user/bot message.
- **Action**: Saves message to `mirt_messages` table.

### 2. `send_followup`
- **Queue**: `followups`
- **Trigger**: Scheduled via dispatcher.
- **Action**: Checks inactivity and sends engagement message.

### 3. `create_crm_order`
- **Queue**: `crm`
- **Trigger**: When payment/order is confirmed.
- **Action**: Pushes order data to Snitkix CRM.

---

## ⚙️ Configuration

Control behavior via `.env`:

- `CELERY_ENABLED=True` -> Tasks go to Redis.
- `CELERY_ENABLED=False` -> Tasks run **synchronously** in the main thread (good for dev/debugging).

---

## 🛠️ Running Workers

### Local
```bash
python scripts/run_worker.py
```

### Docker
Defined in `docker-compose.yml`:
```yaml
  worker:
    build: .
    command: python scripts/run_worker.py
```
