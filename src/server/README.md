# 🌐 src/server — HTTP Layer (FastAPI)

> **Роль:** "Gateway" (Вхідні ворота)
> **Відповідальність:** HTTP endpoints, middleware, routing, dependency injection.

Це **TOP LEVEL** — точка входу HTTP-запитів.
Він імпортує з усіх нижчих шарів: `agents`, `services`, `integrations`, `core`, `conf`.

---

## 📊 Архітектурна Позиція

```
┌─────────────────────────────────────────────────────────────┐
│                     DEPENDENCY PYRAMID                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ━━━━ src/server/ ━━━━  ← YOU ARE HERE (TOP)               │
│          ↓                                                   │
│     src/workers/                                             │
│          ↓                                                   │
│     src/agents/      src/integrations/                      │
│          ↓                ↓                                  │
│     src/services/                                            │
│          ↓                                                   │
│     src/core/                                                │
│          ↓                                                   │
│     src/conf/                                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Структура Директорії

```
src/server/
├── main.py             # 🚀 FastAPI app, lifespan, router registration
├── middleware.py       # 🛡️ Rate limiting, request logging
├── dependencies.py     # 💉 Dependency Injection (Depends)
├── rate_limiter.py     # ⏱️ SlowAPI rate limiting for endpoints
├── models/             # 📦 Pydantic models for API contracts
└── routers/            # 🔀 Endpoints
    ├── webhooks_manychat.py  # ManyChat webhook handler
    ├── api_v1.py             # Public API (messages, CRM updates)
    ├── health.py             # Health checks (comprehensive)
    ├── automation.py         # Internal automation triggers
    ├── media.py              # Media proxy
    ├── common.py             # Shared helpers
    └── schemas.py            # Request/Response schemas
```

---

## 📚 Детальний Опис Файлів

### 🚀 `main.py` — FastAPI Application

Головний файл додатку FastAPI.

| Компонент | Призначення |
| :--- | :--- |
| `lifespan()` | Async context manager для startup/shutdown. Ініціалізує PostgreSQL pool, Memory Service, Checkpointer. |
| `_init_sentry()` | Ініціалізація Sentry SDK для error tracking. |
| `app` | FastAPI instance з усіма роутерами. |

**Lifecycle Events:**
1. **Startup:** PostgreSQL pool, Memory Service, HTTP reachability check.
2. **Shutdown:** Close pools, Checkpointer shutdown.

---

### 💉 `dependencies.py` — Dependency Injection

FastAPI `Depends()` провайдери для чистої ін'єкції.

| Функція | Тип | Призначення |
| :--- | :--- | :--- |
| `get_session_store()` | `@lru_cache` | PostgreSQL session store (fallback: in-memory). |
| `get_message_store()` | `@lru_cache` | Message store для історії. |
| `get_bot()` | `@lru_cache` | Telegram Bot instance. |
| `get_cached_dispatcher()` | Singleton | Telegram Dispatcher. |
| `get_cached_manychat_handler()` | Singleton | ManyChat webhook handler. |
| `reset_dependencies()` | — | Очищення кешів (для тестів). |

**Type Aliases:**
```python
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
MessageStoreDep = Annotated[MessageStore, Depends(get_message_store)]
BotDep = Annotated[Bot, Depends(get_bot)]
```

---

### 🛡️ `middleware.py` — Middleware Stack

| Middleware | Призначення |
| :--- | :--- |
| `RateLimitMiddleware` | In-memory rate limiting (60/min, 1000/hour). |
| `RequestLoggingMiddleware` | Логування всіх HTTP запитів з timing. |

**Rate Limit Config:**
```python
RateLimitConfig(
    requests_per_minute=60,
    requests_per_hour=1000,
    burst_size=10,
    excluded_paths=["/health", "/webhooks/manychat", ...]
)
```

---

### ⏱️ `rate_limiter.py` — SlowAPI Integration

Додатковий rate limiter на базі SlowAPI (Redis-backed для production).

| Декоратор | Ліміти | Використання |
| :--- | :--- | :--- |
| `@limit_auth` | 5/min, 30/hour | Auth endpoints. |
| `@limit_webhook` | 200/min, 5000/hour | Webhook endpoints. |

---

## 🔀 API Endpoints

### 📌 ManyChat Webhook (`/webhooks/manychat`)

**Router:** `routers/webhooks_manychat.py`

| Endpoint | Method | Призначення |
| :--- | :--- | :--- |
| `/webhooks/manychat` | POST | Отримує повідомлення від ManyChat. Returns 202 (async) або response (sync). |
| `/webhooks/manychat/followup` | POST | Follow-up після Smart Delay. |

**Auth:** `X-Manychat-Token` або `Authorization: Bearer`.

---

### 📌 API v1 (`/api/v1`)

**Router:** `routers/api_v1.py`

| Endpoint | Method | Призначення |
| :--- | :--- | :--- |
| `/api/v1/messages` | POST | External Request від ManyChat/n8n. Returns 202. |
| `/api/v1/sitniks/update-status` | POST | Оновлення статусу в CRM (first_touch, give_requisites, escalation). |

**Auth:** `X-API-Key` або `Authorization: Bearer`.

---

### 📌 Health Checks (`/health`)

**Router:** `routers/health.py`

| Endpoint | Method | Призначення |
| :--- | :--- | :--- |
| `/health` | GET | Базовий health check (PostgreSQL, Redis, etc.). |
| `/health/observability` | GET | Перевірка `llm_traces` таблиці. |
| `/health/memory` | GET | Перевірка Memory System. |
| `/health/workers` | GET | Перевірка Celery workers. |
| `/health/preflight` | GET | **ПОВНИЙ** preflight check всіх систем. |

---

### 📌 Automation (`/automation`)

**Router:** `routers/automation.py`

| Endpoint | Method | Призначення |
| :--- | :--- | :--- |
| `/automation/summarize/{session_id}` | POST | Trigger summarization для сесії. |
| `/automation/followup/{session_id}` | POST | Trigger follow-up для сесії. |

---

### 📌 Media (`/media`)

**Router:** `routers/media.py`

Проксі для медіа-файлів (images).

---

## 🔍 Аудит: Чи є Конфлікти?

### ✅ Rate Limiter — НЕ Дублювання

| Файл | Призначення |
| :--- | :--- |
| `core/rate_limiter.py` | **Token bucket** — per-user in-memory limiting (for internal use). |
| `server/rate_limiter.py` | **SlowAPI wrapper** — FastAPI middleware з Redis storage. |
| `server/middleware.py` | **In-memory middleware** — simple sliding window per-IP. |

Вони мають **різне призначення**:
*   `core` — для rate limiting всередині бізнес-логіки.
*   `server/rate_limiter.py` — для endpoint декораторів.
*   `server/middleware.py` — для global middleware.

### ⚠️ Workers → Server Dependency

**Знайдено:** `workers/tasks/manychat.py` імпортує `get_session_store()` з `server.dependencies`.

```python
from src.server.dependencies import get_session_store  # ⚠️ VIOLATION
```

**Проблема:** Workers не повинні залежати від Server (це створює circular risk).

**Рекомендація:** Перемістити `get_session_store()` до `src/services/storage/__init__.py`.

---

## 🛡️ Правила Архітектури

| Правило | Статус |
| :--- | :--- |
| `server → agents` | ✅ Дозволено |
| `server → services` | ✅ Дозволено |
| `server → integrations` | ✅ Дозволено |
| `server → core` | ✅ Дозволено |
| `server → conf` | ✅ Дозволено |
| `workers → server` | ⚠️ **НЕ БАЖАНО** (потребує рефакторингу) |

---

## 📝 Вердикт

`src/server` — це **чистий HTTP layer**.
Він правильно імпортує з нижчих шарів.

**Одна проблема виявлена:** Workers → Server dependency.
Рекомендується рефакторинг `get_session_store()` → `services/storage`.
