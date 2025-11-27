# Mirt-AI

AI-стиліст для бренду дитячого одягу MIRT. Використовує Grok 4.1 fast / GPT-5.1 / Gemini 3 Pro, Pydantic AI, LangGraph v2.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-50%20passed-brightgreen.svg)]()

## 🏗 Архітектура v2

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Telegram   │  │  ManyChat   │  │     Automation API      │  │
│  │  Webhook    │  │  Webhook    │  │  (summarize, followups) │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         └────────────────┼──────────────────────┘                │
│                          ▼                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 LangGraph v2 (5 nodes)                     │  │
│  │                                                             │  │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐               │  │
│  │  │moderation│ → │tool_plan │ → │  agent   │               │  │
│  │  └──────────┘   └──────────┘   └──────────┘               │  │
│  │                                      │                      │  │
│  │  ┌──────────────────┐   ┌───────────┴────────┐            │  │
│  │  │ state_transition │ ← │    validation      │            │  │
│  │  └──────────────────┘   └────────────────────┘            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ▼                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Pydantic AI Agent (Grok/GPT/Gemini)          │  │
│  │    - Embedded Catalog (100 products in prompt)            │  │
│  │    - LLM-specific prompts (data/prompts/)                 │  │
│  │    - Typed AgentResponse output                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ▼                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Supabase (CRM)                          │  │
│  │    - mirt_users (user profiles, summaries)                │  │
│  │    - mirt_messages (chat history)                         │  │
│  │    - agent_sessions (conversation state)                  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 🎯 Key Design Decisions

| Decision | Implementation |
|----------|----------------|
| **FSM Source of Truth** | Code (`src/core/state_machine.py`), NOT prompt |
| **Tool Planning** | Pre-execution in code BEFORE LLM call |
| **Post-Validation** | Without LLM (price > 0, photo_url https://) |
| **Observability** | Structured logs with state/intent/latency tags |
| **LLM Switching** | Config-based (`LLM_PROVIDER=openrouter\|openai\|google`) |

### Ключові компоненти

| Модуль | Призначення |
|--------|-------------|
| `src/core/state_machine.py` | **FSM** — State/Intent enums, transitions, keyboards |
| `src/core/models.py` | Pydantic schemas з enum validators |
| `src/core/tool_planner.py` | Tool planning (disabled, uses Embedded Catalog) |
| `src/core/product_adapter.py` | Product validation (price > 0, https://) |
| `src/core/prompt_loader.py` | LLM-specific prompt loading |
| `src/agents/graph_v2.py` | **5-node LangGraph** orchestration |
| `src/services/message_store.py` | **mirt_messages** — chat history persistence |
| `src/services/summarization.py` | 3-day summary + cleanup |
| `src/services/followups.py` | Follow-up reminders |
| `data/system_prompt_full.yaml` | **Embedded Catalog** — all products in prompt |

### ⚡ Feature Flags

```env
USE_GRAPH_V2=true           # 5-node LangGraph (default: true)
USE_TOOL_PLANNER=true       # Pre-execute tools before LLM
USE_PRODUCT_VALIDATION=true # Validate products before send
USE_INPUT_VALIDATION=true   # Validate metadata enums
ENABLE_OBSERVABILITY=true   # Structured logs with tags
```

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

## Збереження даних у Supabase

### Таблиці

| Таблиця | Призначення |
|---------|-------------|
| `mirt_users` | Профілі користувачів (user_id, username, phone, summary, tags, last_interaction_at) |
| `mirt_messages` | Історія повідомлень (user_id, session_id, role, content, content_type) |
| `agent_sessions` | Стан розмови (session_id, state jsonb) |

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
├── test_manychat_followup.py
└── eval/                      # Golden dataset evaluation
```

## Тести

```bash
# Запуск всіх тестів (50 passed)
pytest

# Тільки v2 архітектура
pytest tests/test_state_machine.py tests/test_product_adapter.py tests/test_graph_v2.py -v

# З coverage
pytest --cov=src --cov-report=html
```

| Test Suite | Tests | Coverage |
|------------|-------|----------|
| `test_state_machine.py` | 21 | FSM transitions, enums |
| `test_product_adapter.py` | 13 | Validation, price/url checks |
| `test_graph_v2.py` | 16 | 5-node graph, mocked LLM |

Тести не викликають зовнішній LLM — використовується `AsyncMock` заглушка.

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
| POST | `/webhooks/manychat/followup` | ManyChat follow-up (4 год) |
| POST | `/webhooks/manychat/create-order` | CRM order creation |
| POST | `/automation/mirt-summarize-prod-v1` | Summarize + cleanup (3 дні) |
| POST | `/automation/mirt-followups-prod-v1` | Follow-up reminders |

## Ліцензія

MIT
