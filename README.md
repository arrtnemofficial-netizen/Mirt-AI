# Mirt-AI

AI-стиліст для бренду дитячого одягу MIRT. Використовує Grok 4.1 fast / GPT-5.1 / Gemini 3 Pro, Pydantic AI, LangGraph v2 та Supabase.

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
│  │    - Supabase tools (search, get_by_id, get_by_photo)     │  │
│  │    - LLM-specific prompts (data/prompts/)                 │  │
│  │    - Typed AgentResponse output                           │  │
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
| `src/core/tool_planner.py` | Pre-LLM tool execution planning |
| `src/core/product_adapter.py` | Product validation (price > 0, https://) |
| `src/core/prompt_loader.py` | LLM-specific prompt loading |
| `src/agents/graph_v2.py` | **5-node LangGraph** orchestration |
| `src/services/observability.py` | Metrics + structured logging |
| `src/services/moderation.py` | PII detection, content filtering |

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
├── core/                      # Domain models та utilities
│   ├── state_machine.py       # ⭐ FSM: State, Intent, Transitions
│   ├── models.py              # Pydantic: AgentResponse, Metadata (enum validators)
│   ├── tool_planner.py        # Pre-LLM tool execution
│   ├── product_adapter.py     # Product validation
│   ├── input_validator.py     # Metadata validation
│   ├── prompt_loader.py       # LLM-specific prompt loading
│   └── constants.py           # Legacy enums (backward compat)
│
├── agents/                    # AI Agent layer
│   ├── graph_v2.py            # ⭐ 5-node LangGraph v2
│   ├── graph.py               # Legacy v1 graph
│   ├── nodes.py               # Graph nodes
│   └── pydantic_agent.py      # Pydantic AI agent + Supabase tools
│
├── services/                  # Business logic
│   ├── observability.py       # ⭐ MetricsCollector, structured logs
│   ├── moderation.py          # PII detection, content filtering
│   ├── supabase_tools.py      # Supabase vector search
│   └── ...
│
├── server/                    # FastAPI layer
├── bot/                       # Telegram integration
└── integrations/              # ManyChat, CRM

data/
├── prompts/                   # ⭐ LLM-specific prompts
│   ├── base.yaml              # Base template
│   ├── grok.yaml              # Grok 4.1 config
│   ├── gpt.yaml               # GPT-5.1 config
│   └── gemini.yaml            # Gemini 3 Pro config
├── system_prompt_full.yaml    # Full prompt (legacy)
├── domain/                    # Business dictionaries
│   ├── states.yaml
│   └── intents.yaml
└── catalog.json               # Product catalog

tests/
├── test_state_machine.py      # 21 FSM tests
├── test_product_adapter.py    # 13 validation tests
├── test_graph_v2.py           # 16 graph v2 tests
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
| POST | `/automation/mirt-summarize-prod-v1` | Summarize old messages |
| POST | `/automation/mirt-followups-prod-v1` | Send follow-up reminders |

## Ліцензія

MIT
