# Source Code Architecture (The Law)

Цей документ визначає структуру папки `src/`. "Кожен крок має свій src" означає, що кожен модуль є самодостатнім і має чіткі межі.

## 🏗️ Core Modules (The Layers)

| Module | Responsibility | Dependencies Allowed | Illegal Dependencies |
|--------|----------------|----------------------|----------------------|
| **`core`** | **Skeleton**. Config, Logging, Shared Types (`State`, `Models`). | None (Base Layer) | `services`, `agents` |
| **`services`** | **Muscles**. Business Logic, DB Access, External APIs. | `core`, `db` | `agents` (Circular!) |
| **`agents`** | **Brain**. LangGraph nodes, LLM calls, Prompts. | `core`, `services` | `bot` |
| **`bot`** | **Mouth**. Telegram/Instagram Adapters. | `agents`, `services`, `core` | None |
| **`server`** | **Face**. FastAPI Routes (REST API). | `agents`, `services`, `core` | `bot` |
| **`workers`** | **Limbs**. Celery Tasks (Async). | `agents`, `services`, `core` | `server` |

---

## 📂 Directory Map (Honest Audit)

### `/src/agents`
*   **Role**: Вся логіка прийняття рішень (LLM).
*   **Structure**:
    *   `langgraph/`: Flow definitions (Graphs, Nodes, Edges).
    *   `pydantic/`: Structured output models & PydanticAI agents.
*   **Rule**: Ніяких прямих SQL запитів тут. Тільки через `services`.

### `/src/services`
*   **Role**: "Heavy lifting".
*   **Structure**:
    *   `storage/`: DB access (Repositories).
    *   `llm/`: Resilience (Fallbacks, Circuit Breakers), NOT business logic.
    *   `conversation/`: Chat history management, Parsers.
    *   `catalog/`: Product lookup.
*   **Rule**: Кожен сервіс має бути ізольованим.

### `/src/bot`
*   **Role**: Тільки адаптери для месенджерів.
*   **Status**: Зараз там тільки `telegram_bot.py`. Це ок. Якщо додамо Instagram, створимо `src/bot/instagram/`.

### `/src/core`
*   **Role**: Shared code.
*   **Contents**: `config.py`, `logging.py`, `models.py`.
*   **Rule**: Якщо цей код використовується в >2 модулях, йому місце тут.

### `/src/db`
*   **Role**: SQL Schema definitions & Migrations.
*   **Note**: Це не код доступу до БД (це в `services/storage`). Це файли `.sql`.

---

## 🚫 Forbidden Patterns (Kill on Sight)

1.  **Circular Imports**: `services` imports `agents`. (Гріх).
2.  **God Objects**: Файли > 1000 рядків (окрім, на жаль, `agent.py` - ми працюємо над цим).
3.  **Cross-Service Leaks**: Один сервіс лізе в приватні методи іншого.

## ✅ Clean Steps Taken
1.  Verified separation of `agents` vs `services`.
2.  Verified `bot` is just a presentation layer.
3.  **Deleted** `src/services/client_data_parser_minimal.py` (Dead code, logic lives in `payment_agent.py`).

Ця структура гарантує, що "нічого не зламано і не конфліктує".
