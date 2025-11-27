# Mirt-AI

AI-стиліст для бренду дитячого одягу MIRT. Використовує Grok 4.1 fast (OpenRouter), Pydantic AI, LangGraph та Supabase.

[![CI](https://github.com/mirt/mirt-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/mirt/mirt-ai/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Архітектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Telegram   │  │  ManyChat   │  │     Automation API      │  │
│  │  Webhook    │  │  Webhook    │  │  (summarize, followups) │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         │                │                      │                │
│         └────────────────┼──────────────────────┘                │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              ConversationHandler (centralized)             │  │
│  │    - Error handling with graceful fallbacks                │  │
│  │    - Message persistence                                   │  │
│  │    - Session state management                              │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ▼                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    LangGraph Orchestrator                  │  │
│  │    - State machine (STATE0_INIT → STATE9_OOD)             │  │
│  │    - Moderation layer                                      │  │
│  │    - Agent invocation                                      │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ▼                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Pydantic AI Agent (Grok 4.1 fast)            │  │
│  │    - Supabase tools (search, get_by_id, get_by_photo)     │  │
│  │    - Typed AgentResponse output                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Ключові компоненти

| Модуль | Призначення |
|--------|-------------|
| `src/core/constants.py` | Type-safe Enums (AgentState, MessageTag, EscalationLevel) |
| `src/core/validation.py` | Input validation, SQL injection protection |
| `src/core/logging.py` | Structured JSON logging для production |
| `src/services/conversation.py` | Централізований ConversationHandler з error handling |
| `src/server/middleware.py` | Rate limiting (60 req/min) + request logging |
| `src/server/dependencies.py` | FastAPI Dependency Injection |
| `src/services/moderation.py` | PII detection, leetspeak normalization |

### Clean Code принципи
- **No magic strings** — всі стани та теги через Enums
- **Dependency Injection** — FastAPI Depends() замість глобальних синглтонів
- **Centralized error handling** — graceful fallbacks у ConversationHandler
- **Input validation** — захист від SQL injection та pattern injection
- **Structured logging** — JSON формат для production, pretty для dev

## Швидкий старт

### Варіант 1: Docker (рекомендовано)

```bash
# Скопіюйте .env.example та заповніть значення
cp .env.example .env

# Запустіть
docker-compose up -d

# Перевірте health
curl http://localhost:8000/health
```

### Варіант 2: Локально

```bash
# Створіть venv
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Встановіть залежності
pip install -r requirements.txt

# Скопіюйте та налаштуйте .env
cp .env.example .env

# Запустіть сервер
uvicorn src.server.main:app --reload
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

## Збереження сесій, повідомлень і каталогу у Supabase
- Сесії: таблиця `SUPABASE_TABLE` із полями `session_id` (PK, text) і `state` (jsonb). Автоматичне перемикання на Supabase при наявності env.
- Повідомлення: таблиця `SUPABASE_MESSAGES_TABLE` з полями `session_id`, `role`, `content`, `created_at` (timestamptz), `tags` (array/text[]). Усі вхідні та вихідні повідомлення записуються туди; тег `humanNeeded-wd` ставиться на відповіді з ескалацією.
- Каталог (RAG): таблиця `mirt_products` з полями з system prompt (category/subcategory/sizes/material/price_uniform/price_by_size/colors). Ембеддинги — таблиця `mirt_product_embeddings` (vector(1536)), RPC `match_mirt_products` повертає top-N. `data/catalog.json` та `data/catalog.csv` слугують єдиним джерелом для імпорту.

## ManyChat / Instagram webhook
- Ендпоінт: `POST /webhooks/manychat` приймає ManyChat payload (`subscriber.id`, `message.text`).
- Авторизація: заголовок `X-Manychat-Token` має збігатися з `MANYCHAT_VERIFY_TOKEN` у `.env`.
- Відповідь: `{version:"v2", messages:[{type:"text",text:"..."},...], metadata:{current_state,...}}` — сумісно з ManyChat reply API.

### Автоматизація переупаковки
- Ендпоінт: `POST /automation/mirt-summarize-prod-v1` з тілом `{ "session_id": "..." }`.
- Логіка: якщо від останнього повідомлення минуло `SUMMARY_RETENTION_DAYS` днів (за замовчуванням 3), усі повідомлення по `session_id` перетворюються у саммарі, записуються у поле `summary` таблиці `SUPABASE_USERS_TABLE`, старі повідомлення видаляються з `SUPABASE_MESSAGES_TABLE`.
- При переупаковці тег `humanNeeded-wd` автоматично знімається, щоб закрити SLA ескалації.

### Автоматизація фолоуапів
- Ендпоінт: `POST /automation/mirt-followups-prod-v1` з тілом `{ "session_id": "...", "schedule_hours": [24, 72] }`.
- Якщо `schedule_hours` не заданий, використовується `FOLLOWUP_DELAYS_HOURS` з `.env` (кома-сепарований список годин). Система перевіряє дату останньої активності та кількість уже відправлених фолоуапів (теги `followup-sent-*` у таблиці повідомлень) і, якщо настав час, записує нове повідомлення з нагадуванням у `SUPABASE_MESSAGES_TABLE`.
- Відправку повідомлень на канали (Telegram, ManyChat) можна реалізувати власним шедулером: достатньо викликати цей ендпоінт і надіслати сформований текст на потрібний канал.

## Структура проекту

```
src/
├── core/                    # Domain models та utilities
│   ├── constants.py         # Enums: AgentState, MessageTag, EscalationLevel
│   ├── models.py            # Pydantic: AgentResponse, Product, Message
│   ├── validation.py        # Input validation, SQL injection protection
│   └── logging.py           # Structured JSON/Pretty logging
│
├── agents/                  # AI Agent layer
│   ├── graph.py             # LangGraph orchestrator
│   ├── nodes.py             # Graph nodes (agent_node)
│   └── pydantic_agent.py    # Pydantic AI agent + Supabase tools
│
├── server/                  # FastAPI layer
│   ├── main.py              # ASGI app, endpoints, lifespan
│   ├── dependencies.py      # DI providers (Depends)
│   └── middleware.py        # Rate limiting, request logging
│
├── services/                # Business logic
│   ├── conversation.py      # ConversationHandler (centralized)
│   ├── moderation.py        # PII detection, content filtering
│   ├── supabase_tools.py    # Supabase vector search + validation
│   ├── session_store.py     # Session persistence (memory/Supabase)
│   ├── message_store.py     # Message persistence
│   ├── followups.py         # Follow-up automation
│   └── summarization.py     # Message retention & summarization
│
├── bot/                     # Telegram integration
│   └── telegram_bot.py      # Aiogram handlers
│
└── integrations/            # External platforms
    └── manychat/webhook.py  # ManyChat/Instagram DM

data/
├── system_prompt_full.yaml  # AI personality & state machine
├── catalog.json             # Product catalog (JSON)
└── catalog.csv              # Catalog with embeddings (for Supabase import)
```

## Тести

```bash
# Запуск всіх тестів
pytest

# З coverage
pytest --cov=src --cov-report=html

# Docker
docker-compose --profile test up tests
```

Тести не викликають зовнішній LLM — використовується `DummyAgent` заглушка.

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`):
- **Lint** — Ruff linter + formatter
- **Type Check** — MyPy
- **Test** — pytest з coverage
- **Docker Build** — перевірка збірки образу
- **Security** — Bandit + Safety

## Безпека

| Захист | Реалізація |
|--------|------------|
| Rate Limiting | 60 req/min per IP |
| SQL Injection | `validation.py` sanitization |
| Pattern Injection | `escape_like_pattern()` |
| PII Detection | Email, phone, card, passport regex |
| Leetspeak Bypass | Unicode normalization + substitution map |
| Input Validation | Product ID, URL, session ID validators |

## API Endpoints

| Method | Path | Опис |
|--------|------|------|
| GET | `/health` | Health check |
| POST | `/webhooks/telegram` | Telegram webhook |
| POST | `/webhooks/manychat` | ManyChat webhook |
| POST | `/automation/mirt-summarize-prod-v1` | Summarize old messages |
| POST | `/automation/mirt-followups-prod-v1` | Send follow-up reminders |

## Ліцензія

MIT
