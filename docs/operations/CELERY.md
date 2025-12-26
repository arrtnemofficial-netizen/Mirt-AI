# Celery & Background Tasks

> 📚 **Центральний індекс:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

## Overview

MIRT AI uses Celery for tasks that shouldn't block the main request loop, such as:
- Logging messages to Supabase.
- Sending proactive follow-ups.
- Syncing orders to CRM.
- **Memory maintenance** (time decay, cleanup).

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

### 4. `memory_time_decay` (Scheduled)
- **File**: `src/services/memory_tasks.py`
- **Trigger**: Daily cron at 3:00 AM.
- **Action**: Reduces `importance` of old facts in `mirt_memories`.

### 5. `memory_cleanup` (Scheduled)
- **File**: `src/services/memory_tasks.py`
- **Trigger**: Daily cron at 4:00 AM.
- **Action**: Deletes facts with `importance < 0.3`.

### 6. `generate_memory_summaries` (Scheduled)
- **File**: `src/services/memory_tasks.py`
- **Trigger**: Weekly.
- **Action**: Creates compressed summaries for active users in `mirt_memory_summaries`.

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
