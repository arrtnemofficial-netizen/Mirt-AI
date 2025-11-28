# Mirt-AI

AI-стиліст для бренду дитячого одягу MIRT. Використовує Grok 4.1 fast / GPT-5.1 / Gemini 3 Pro, Pydantic AI, LangGraph v2, **Celery + Redis** для фонових задач.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-68%20passed-brightgreen.svg)]()
[![Celery](https://img.shields.io/badge/Celery-5.4+-green.svg)](https://docs.celeryq.dev/)

## 🏗 Архітектура v2

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FastAPI Server                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐          │
│  │  Telegram   │  │  ManyChat   │  │     Automation API      │          │
│  │  Webhook    │  │  Webhook    │  │  (summarize, followups) │          │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘          │
│         └────────────────┼──────────────────────┘                        │
│                          ▼                                               │
│  ┌───────────────────────────────────────────────────────────┐          │
│  │                    Dispatcher                              │          │
│  │   CELERY_ENABLED=true  →  Celery Queue                    │          │
│  │   CELERY_ENABLED=false →  Sync Execution                  │          │
│  └─────────────────────────────┬─────────────────────────────┘          │
└────────────────────────────────┼────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────────┐
        │                        ▼                            │
        │  ┌─────────────────────────────────────────────┐   │
        │  │              Redis Broker                    │   │
        │  │         (redis://localhost:6379)             │   │
        │  └─────────────────────────────────────────────┘   │
        │                        │                            │
        │     ┌──────────────────┼──────────────────┐        │
        │     ▼                  ▼                  ▼        │
        │  ┌──────┐  ┌──────────────┐  ┌──────────────┐      │
        │  │ LLM  │  │ Summarization │  │  Follow-ups  │     │
        │  │Queue │  │    Queue      │  │    Queue     │     │
        │  └──┬───┘  └──────┬───────┘  └──────┬───────┘      │
        │     │             │                 │               │
        │     ▼             ▼                 ▼               │
        │  ┌─────────────────────────────────────────────┐   │
        │  │           Celery Workers (4x)               │   │
        │  │  • process_message (AI agent)               │   │
        │  │  • summarize_session (3-day cleanup)        │   │
        │  │  • send_followup (reminders)                │   │
        │  │  • create_crm_order (Snitkix)               │   │
        │  └─────────────────────────────────────────────┘   │
        │                        │                            │
        │  ┌─────────────────────────────────────────────┐   │
        │  │           Celery Beat (Scheduler)           │   │
        │  │  • health-check: every 5 min                │   │
        │  │  • followups-check: every 15 min            │   │
        │  │  • summarization-check: every 1 hour        │   │
        │  └─────────────────────────────────────────────┘   │
        │                                                     │
        │                 CELERY WORKERS                      │
        └─────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ┌───────────────────────────────────────────────────────────┐          │
│  │                 LangGraph v2 (5 nodes)                     │          │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐               │          │
│  │  │moderation│ → │tool_plan │ → │  agent   │               │          │
│  │  └──────────┘   └──────────┘   └──────────┘               │          │
│  │                                      │                      │          │
│  │  ┌──────────────────┐   ┌───────────┴────────┐            │          │
│  │  │ state_transition │ ← │    validation      │            │          │
│  │  └──────────────────┘   └────────────────────┘            │          │
│  └───────────────────────────────────────────────────────────┘          │
│                            ▼                                             │
│  ┌───────────────────────────────────────────────────────────┐          │
│  │              Pydantic AI Agent (Grok/GPT/Gemini)          │          │
│  │    - Embedded Catalog (100 products in prompt)            │          │
│  │    - LLM-specific prompts (data/prompts/)                 │          │
│  └───────────────────────────────────────────────────────────┘          │
│                            ▼                                             │
│  ┌───────────────────────────────────────────────────────────┐          │
│  │                    Supabase (CRM)                          │          │
│  │    - mirt_users (user profiles, summaries)                │          │
│  │    - mirt_messages (chat history)                         │          │
│  │    - agent_sessions (conversation state)                  │          │
│  └───────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 🎯 Key Design Decisions

| Decision                | Implementation                                           |
| ----------------------- | -------------------------------------------------------- |
| **FSM Source of Truth** | Code (`src/core/state_machine.py`), NOT prompt           |
| **Tool Planning**       | Pre-execution in code BEFORE LLM call                    |
| **Post-Validation**     | Without LLM (price > 0, photo_url https://)              |
| **Observability**       | Structured logs with state/intent/latency tags           |
| **LLM Switching**       | Config-based (`LLM_PROVIDER=openrouter\|openai\|google`) |
| **Background Tasks**    | Celery + Redis with separate queues per task type        |
| **Async in Workers**    | `run_sync()` facade, no `asyncio.run()` per task         |
| **Idempotency**         | Task ID from webhook message_id for deduplication        |

### Ключові компоненти

| Модуль                          | Призначення                                          |
| ------------------------------- | ---------------------------------------------------- |
| `src/core/state_machine.py`     | **FSM** — State/Intent enums, transitions, keyboards |
| `src/core/models.py`            | Pydantic schemas з enum validators                   |
| `src/core/tool_planner.py`      | Tool planning (disabled, uses Embedded Catalog)      |
| `src/core/product_adapter.py`   | Product validation (price > 0, https://)             |
| `src/core/prompt_loader.py`     | LLM-specific prompt loading                          |
| `src/agents/graph_v2.py`        | **5-node LangGraph** orchestration                   |
| `src/services/message_store.py` | **mirt_messages** — chat history persistence         |
| `src/services/summarization.py` | 3-day summary + cleanup                              |
| `src/services/followups.py`     | Follow-up reminders                                  |
| `src/workers/celery_app.py`     | **Celery** — 12 tasks, 6 queues, beat schedule       |
| `src/workers/dispatcher.py`     | **Dispatcher** — routes to Celery or sync            |
| `src/workers/tasks/messages.py` | **process_message** — main AI processing task        |
| `data/system_prompt_full.yaml`  | **Embedded Catalog** — all products in prompt        |

### ⚡ Feature Flags

```env
USE_GRAPH_V2=true           # 5-node LangGraph (default: true)
USE_TOOL_PLANNER=true       # Pre-execute tools before LLM
USE_PRODUCT_VALIDATION=true # Validate products before send
USE_INPUT_VALIDATION=true   # Validate metadata enums
ENABLE_OBSERVABILITY=true   # Structured logs with tags
CELERY_ENABLED=true         # Enable Celery workers (requires Redis)
CELERY_EAGER=true           # Run tasks sync (for testing)
```

## Швидкий старт

### Варіант 1: Docker з Celery (рекомендовано для production)

```bash
# Скопіюйте .env.example та заповніть значення
cp .env.example .env

# Запустіть всі сервіси (app + redis + celery worker + celery beat)
docker-compose up -d

# Перевірте health
curl http://localhost:8000/health

# Опційно: моніторинг Flower
docker-compose --profile monitoring up -d
# Відкрийте http://localhost:5555
```

### Варіант 2: Локально без Celery (для розробки)

```bash
# Створіть venv
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Встановіть залежності
pip install -r requirements.txt

# Скопіюйте та налаштуйте .env
cp .env.example .env

# CELERY_ENABLED=false (default) — синхронна обробка
uvicorn src.server.main:app --reload
```

### Варіант 3: Локально з Celery

```bash
# Термінал 1: Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Термінал 2: Celery Worker
celery -A src.workers.celery_app worker --loglevel=INFO --queues=default,llm,summarization,followups,crm,webhooks

# Термінал 3: Celery Beat (scheduler)
celery -A src.workers.celery_app beat --loglevel=INFO

# Термінал 4: FastAPI з CELERY_ENABLED=true
CELERY_ENABLED=true uvicorn src.server.main:app --reload
```

### Демо-виклик

```python
from src.agents.graph import app
from src.core import AgentState
import asyncio

state = {
    "messages": [{"role": "user", "content": "Привіт! Потрібна червона сукня 122 см."}],
    "metadata": {"session_id": "demo"},
    "current_state": AgentState.STATE1_DISCOVERY,
}

result = asyncio.run(app.ainvoke(state))
print(result)
```

## Телеграм бот
- **Локально (polling)**: `python -m src.bot.telegram_bot` або виклик `run_polling()` у коді. Достатньо вставити свій `TELEGRAM_BOT_TOKEN` у `.env`.
- **Webhook**: підніміть FastAPI `uvicorn src.server.main:app --host 0.0.0.0 --port 8000`, задайте `PUBLIC_BASE_URL` (публічна адреса reverse-proxy/NGROK) — вебхук реєструється автоматично на старті.

## Збереження даних у Supabase

### Таблиці

| Таблиця          | Призначення                                                                         |
| ---------------- | ----------------------------------------------------------------------------------- |
| `mirt_users`     | Профілі користувачів (user_id, username, phone, summary, tags, last_interaction_at) |
| `mirt_messages`  | Історія повідомлень (user_id, session_id, role, content, content_type)              |
| `agent_sessions` | Стан розмови (session_id, state jsonb)                                              |

### Як працює

1. **Клієнт пише** → повідомлення зберігається в `mirt_messages` з `user_id`
2. **Бот відповідає** → відповідь зберігається в `mirt_messages`
3. **При кожному повідомленні** → оновлюється `last_interaction_at` в `mirt_users`
4. **Через 3 дні** → ManyChat викликає `/automation/mirt-summarize-prod-v1` → summary зберігається в `mirt_users.summary`, старі повідомлення видаляються

### Каталог товарів

**Embedded Catalog** — всі товари (~100) вбудовані прямо в системний промпт (`data/system_prompt_full.yaml`).
- Без RAG, без векторного пошуку
- LLM шукає товари прямо в промпті
- Швидше та дешевше для малого каталогу

## ManyChat / Instagram webhook
- Ендпоінт: `POST /webhooks/manychat` приймає ManyChat payload (`subscriber.id`, `message.text`).
- Авторизація: заголовок `X-Manychat-Token` має збігатися з `MANYCHAT_VERIFY_TOKEN` у `.env`.
- Відповідь: `{version:"v2", messages:[{type:"text",text:"..."},...], metadata:{current_state,...}}` — сумісно з ManyChat reply API.

### Автоматизація переупаковки (3 дні)

```
ManyChat Smart Delay (3 дні) → POST /automation/mirt-summarize-prod-v1
                                    ↓
                              { "user_id": 12345, "session_id": "12345", "action": "summarize" }
                                    ↓
                              1. Беремо всі повідомлення з mirt_messages
                              2. Генеруємо summary
                              3. Зберігаємо в mirt_users.summary
                              4. Видаляємо старі повідомлення
                              5. Повертаємо { "action": "remove_tags" }
                                    ↓
                              ManyChat знімає тег humanNeeded-wd
```

### Автоматизація фолоуапів (4 години)

```
ManyChat Smart Delay (4 год) → POST /webhooks/manychat/followup
                                    ↓
                              { "subscriber": {"id": "12345"}, "custom_fields": {"ai_state": "STATE_4_OFFER"} }
                                    ↓
                              Бот генерує follow-up текст на основі стану
                                    ↓
                              { "needs_followup": true, "followup_text": "Ще раздумуєте над замовленням?" }
                                    ↓
                              ManyChat відправляє текст клієнту
```

## Структура проекту

```
src/
├── core/                      # Domain models та utilities
│   ├── state_machine.py       # ⭐ FSM: State, Intent, Transitions
│   ├── models.py              # Pydantic: AgentResponse, Metadata
│   ├── tool_planner.py        # Tool planning (disabled)
│   ├── product_adapter.py     # Product validation
│   ├── input_validator.py     # Metadata validation
│   ├── prompt_loader.py       # LLM-specific prompt loading
│   └── validation.py          # Input sanitization
│
├── agents/                    # AI Agent layer
│   ├── graph_v2.py            # ⭐ 5-node LangGraph v2
│   ├── graph.py               # Legacy v1 graph
│   ├── nodes.py               # Graph nodes
│   └── pydantic_agent.py      # Pydantic AI agent
│
├── services/                  # Business logic
│   ├── message_store.py       # ⭐ mirt_messages persistence
│   ├── summarization.py       # 3-day summary + cleanup
│   ├── followups.py           # Follow-up reminders
│   ├── supabase_client.py     # Supabase connection
│   ├── supabase_store.py      # Session persistence
│   └── moderation.py          # PII detection
│
├── workers/                   # ⭐ Celery background tasks
│   ├── celery_app.py          # Celery config, 6 queues, beat schedule
│   ├── dispatcher.py          # Routes to Celery or sync
│   ├── sync_utils.py          # run_sync() for async in workers
│   ├── exceptions.py          # RetryableError, PermanentError
│   ├── idempotency.py         # Task deduplication
│   └── tasks/
│       ├── messages.py        # ⭐ process_message (AI agent)
│       ├── summarization.py   # summarize_session
│       ├── followups.py       # send_followup
│       ├── crm.py             # create_crm_order
│       └── health.py          # worker_health_check, ping
│
├── server/                    # FastAPI layer
│   ├── main.py                # ⭐ All endpoints
│   ├── dependencies.py        # DI
│   └── middleware.py          # Rate limiting
│
├── bot/                       # Telegram integration
└── integrations/              # ManyChat, CRM

data/
├── system_prompt_full.yaml    # ⭐ EMBEDDED CATALOG (all products)
├── prompts/                   # LLM-specific prompts
│   ├── base.yaml
│   ├── grok.yaml
│   ├── gpt.yaml
│   └── gemini.yaml
├── domain/
│   ├── states.yaml
│   └── intents.yaml
└── catalog.json               # Product catalog (for tests)

tests/
├── test_state_machine.py
├── test_product_adapter.py
├── test_graph_v2.py
├── test_workers_integration.py # ⭐ 18 Celery tests
├── test_manychat_followup.py
└── eval/                      # Golden dataset evaluation
```

## Тести

```bash
# Запуск всіх тестів (68+ passed)
pytest

# Тільки v2 архітектура
pytest tests/test_state_machine.py tests/test_product_adapter.py tests/test_graph_v2.py -v

# Тільки Celery workers
pytest tests/test_workers_integration.py -v

# З coverage
pytest --cov=src --cov-report=html
```

| Test Suite                    | Tests | Coverage                              |
| ----------------------------- | ----- | ------------------------------------- |
| `test_state_machine.py`       | 21    | FSM transitions, enums                |
| `test_product_adapter.py`     | 13    | Validation, price/url checks          |
| `test_graph_v2.py`            | 16    | 5-node graph, mocked LLM              |
| `test_workers_integration.py` | 18    | Celery tasks, sync_utils, idempotency |

Тести не викликають зовнішній LLM — використовується `AsyncMock` заглушка.
Celery тести використовують `CELERY_TASK_ALWAYS_EAGER=True`.

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`):
- **Lint** — Ruff linter + formatter
- **Type Check** — MyPy
- **Test** — pytest з coverage
- **Docker Build** — перевірка збірки образу
- **Security** — Bandit + Safety

## Безпека

| Захист            | Реалізація                               |
| ----------------- | ---------------------------------------- |
| Rate Limiting     | 60 req/min per IP                        |
| SQL Injection     | `validation.py` sanitization             |
| Pattern Injection | `escape_like_pattern()`                  |
| PII Detection     | Email, phone, card, passport regex       |
| Leetspeak Bypass  | Unicode normalization + substitution map |
| Input Validation  | Product ID, URL, session ID validators   |

## API Endpoints

| Method | Path                                 | Опис                                 |
| ------ | ------------------------------------ | ------------------------------------ |
| GET    | `/health`                            | Health check (+ Redis/Celery status) |
| POST   | `/webhooks/telegram`                 | Telegram webhook                     |
| POST   | `/webhooks/manychat`                 | ManyChat webhook                     |
| POST   | `/webhooks/manychat/followup`        | ManyChat follow-up (4 год)           |
| POST   | `/webhooks/manychat/create-order`    | CRM order creation                   |
| POST   | `/automation/mirt-summarize-prod-v1` | Summarize + cleanup (→ Celery)       |
| POST   | `/automation/mirt-followups-prod-v1` | Follow-up reminders (→ Celery)       |

## 🔄 Celery Workers

### Черги (Queues)

| Queue           | Tasks                                     | Time Limit |
| --------------- | ----------------------------------------- | ---------- |
| `llm`           | `process_message`, `process_and_respond`  | 60s        |
| `summarization` | `summarize_session`, `check_all_sessions` | 120s       |
| `followups`     | `send_followup`, `schedule_followup`      | 60s        |
| `crm`           | `create_crm_order`, `sync_order_status`   | 30s        |
| `webhooks`      | `send_response`                           | 30s        |
| `default`       | `ping`, `worker_health_check`             | 10s        |

### Таски (12 total)

| Task                  | Опис                                                   |
| --------------------- | ------------------------------------------------------ |
| `process_message`     | ⭐ Головний таск — обробка повідомлення через AI агента |
| `process_and_respond` | Fire-and-forget: обробка + відправка відповіді         |
| `send_response`       | Відправка відповіді в Telegram/ManyChat                |
| `summarize_session`   | Генерація summary + видалення старих повідомлень       |
| `send_followup`       | Відправка follow-up нагадування                        |
| `create_crm_order`    | Створення замовлення в Snitkix CRM                     |
| `worker_health_check` | Перевірка стану worker (Redis, Supabase)               |

### Beat Schedule (periodic)

| Job                      | Інтервал | Task                                   |
| ------------------------ | -------- | -------------------------------------- |
| `health-check-5min`      | 5 хв     | `worker_health_check`                  |
| `followups-check-15min`  | 15 хв    | `check_all_sessions_for_followups`     |
| `summarization-check-1h` | 1 год    | `check_all_sessions_for_summarization` |

### Production Config

```env
# Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_ENABLED=true
CELERY_CONCURRENCY=4
CELERY_MAX_TASKS_PER_CHILD=100

# Monitoring (optional)
SENTRY_DSN=https://xxx@sentry.io/xxx
SENTRY_ENVIRONMENT=production
```

### Моніторинг

```bash
# Flower UI (http://localhost:5555)
docker-compose --profile monitoring up -d

# CLI: перевірка workers
celery -A src.workers.celery_app inspect active

# CLI: статистика черг
celery -A src.workers.celery_app inspect stats
```

## Ліцензія

MIT
