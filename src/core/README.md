# 🧱 src/core — Фундаментний Шар (Foundation Layer)

> **Роль:** "Bedrock" (Підвалина)
> **Відповідальність:** Базові типи, контракти та патерни, які використовуються **ВСІМА** шарами системи.

Це **ДРУГИЙ НАЙНИЖЧИЙ ШАР** (після `src/conf`).
Він НЕ імпортує з `agents/`, `services/`, `server/`, `workers/`.

---

## 📊 Архітектурна Позиція

```
┌─────────────────────────────────────────────────────────────┐
│                     DEPENDENCY PYRAMID                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│     src/server/      src/workers/      src/bot/             │
│          ↓                ↓                ↓                │
│                    src/agents/                               │
│                         ↓                                    │
│     src/services/    src/integrations/                      │
│          ↓                ↓                                  │
│   ━━━━ src/core/ ━━━━  ← YOU ARE HERE                       │
│          ↓                                                   │
│   ━━━━ src/conf/ ━━━━  ← FOUNDATION                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Структура та Призначення Файлів

```
src/core/
├── __init__.py           # Експорти всіх публічних API
├── state_machine.py      # 🔄 SSOT: State, Intent, Transitions (FSM)
├── models.py             # 📦 SSOT: AgentResponse, Product, Message, Metadata
├── constants.py          # 📊 Константи: DBTable, MessageTag (deprecated aliases)
├── circuit_breaker.py    # 🔌 SSOT: CircuitBreaker патерн
├── prompt_registry.py    # 📜 Реєстр промптів з data/prompts/
├── human_responses.py    # 💬 Fallback людські відповіді
├── fallbacks.py          # 🛡️ Graceful degradation responses
├── input_validator.py    # ✅ Валідація вхідних даних webhook
├── input_sanitizer.py    # 🧹 Санітизація user input
├── product_adapter.py    # 🔄 Адаптер для продуктів (YAML → Model)
├── rate_limiter.py       # ⏱️ Rate limiting (token bucket)
├── debug_logger.py       # 🐛 Debug logging utilities
└── logging.py            # 📝 Rich logging configuration
```

---

## 📚 Детальний Опис Файлів

### 🔄 `state_machine.py` — FSM (SSOT)

**Це СЕРЦЕ системи.** Визначає всі стани діалогу та правила переходів.

| Клас/Enum | Призначення |
| :--- | :--- |
| `State` | Enum станів FSM: `STATE_0_INIT` → `STATE_7_END` |
| `Intent` | Enum інтентів: `GREETING_ONLY`, `PAYMENT_CONFIRM`, etc. |
| `Transition` | Правило переходу: `from_state` → `to_state` при `intents` |
| `TRANSITIONS` | Повна таблиця FSM переходів |
| `get_next_state()` | Обчислення наступного стану |

**Хто імпортує:**
- `src/agents/langgraph/` — всі nodes та edges
- `src/services/guardrails/loop_detector.py`
- `src/services/conversation/conversation.py`

---

### 📦 `models.py` — Data Contracts (SSOT)

Типізовані контракти для обміну даними між шарами.

| Клас | Призначення |
| :--- | :--- |
| `BaseConversationState` | TypedDict для стану сесії |
| `AgentResponse` | OUTPUT_CONTRACT від AI агента |
| `Product` | Товар з каталогу |
| `Message` | Одне повідомлення (text/image) |
| `Metadata` | Технічні метадані кроку |
| `Escalation` | Опис ескалації |

**Хто імпортує:**
- `src/agents/pydantic/models.py`
- `src/services/parser/output_parser.py`
- `src/services/conversation/conversation.py`

---

### 🔌 `circuit_breaker.py` — CircuitBreaker (SSOT)

Патерн захисту від каскадних відмов.

| Експорт | Призначення |
| :--- | :--- |
| `CircuitBreaker` | Клас з state machine (CLOSED → OPEN → HALF_OPEN) |
| `CircuitState` | Enum станів breaker'а |
| `get_circuit_breaker()` | Отримати/створити breaker за ім'ям (singleton) |
| `@circuit_breaker` | Декоратор для функцій |

**Хто імпортує:**
- `src/services/llm/llm_fallback.py`
- `src/agents/pydantic/circuit_breaker.py`

---

### 📜 `prompt_registry.py` — Prompt Registry

Централізований реєстр промптів з `data/prompts/`.

| Функція | Призначення |
| :--- | :--- |
| `registry.get_prompt(state)` | Отримати промпт для стану |
| `registry.get_snippets()` | Отримати всі сніпети |
| `validate_all_states_have_prompts()` | Перевірка повноти промптів |

**Хто імпортує:**
- `src/agents/pydantic/support_agent.py`
- `src/agents/langgraph/state_prompts.py`

---

### 💬 `human_responses.py` — Fallback Messages

Людські відповіді для graceful degradation.

```python
from src.core.human_responses import get_human_response

# При помилці AI — повертаємо людську відповідь
response = get_human_response("error_general")
```

---

### 📊 `constants.py` — Константи (Deprecated Aliases)

> ⚠️ **DEPRECATED:** Використовуйте `state_machine.py` напряму.

Цей файл існує для backward compatibility. Новий код повинен імпортувати з `state_machine.py`.

```python
# OLD (deprecated)
from src.core.constants import AgentState

# NEW (correct)
from src.core.state_machine import State
```

---

## 🛡️ Залізобетонні Правила

| Правило | Статус |
| :--- | :--- |
| `core → agents` | ❌ **ЗАБОРОНЕНО** |
| `core → services` | ❌ **ЗАБОРОНЕНО** |
| `core → server` | ❌ **ЗАБОРОНЕНО** |
| `core → workers` | ❌ **ЗАБОРОНЕНО** |
| `core → conf` | ✅ **Дозволено** (conf нижче) |
| `core → core` | ✅ **Дозволено** (internal imports) |

> ⚠️ Ці правила перевіряються автоматично через `scripts/check_imports.py`.

---

## 📈 Статистика Використання

| Шар | Кількість імпортів з core |
| :--- | :--- |
| `src/agents/langgraph/` | ~35 файлів |
| `src/agents/pydantic/` | ~15 файлів |
| `src/services/` | ~15 файлів |
| `src/server/` | ~3 файли |

---

## 🔀 Import Cheat Sheet

```python
# State Machine (SSOT)
from src.core.state_machine import State, Intent, get_next_state

# Data Models (SSOT)
from src.core.models import AgentResponse, Product, Message, Metadata

# Circuit Breaker (SSOT)
from src.core.circuit_breaker import get_circuit_breaker, circuit_breaker

# Prompt Registry
from src.core.prompt_registry import registry

# Fallbacks
from src.core.human_responses import get_human_response
from src.core.fallbacks import get_fallback_response

# Debug
from src.core.debug_logger import debug_log

# Input Processing
from src.core.input_validator import validate_input_metadata
from src.core.input_sanitizer import process_user_message
```

---

## 📝 Вердикт

`src/core` — це **фундамент архітектури**.
Усі типи, контракти та патерни живуть тут.

**Конфліктів немає.** Core імпортує тільки з conf (нижчий шар).
Усі інші шари імпортують з core — це правильний напрямок залежностей.
