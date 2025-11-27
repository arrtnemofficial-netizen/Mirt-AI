# MIRT AI Architecture

## Overview

MIRT AI — це AI-консультант для магазину дитячого одягу, побудований на:
- **LangGraph v2** — 5-вузлова оркестрація (moderation → tool_plan → agent → validation → state_transition)
- **Pydantic AI** — типізований агент
- **Supabase** — база даних та семантичний пошук
- **Grok 4.1 Fast / GPT-5.1** — LLM провайдери

### Key Architecture Decisions

1. **FSM Source of Truth**: Код (`src/core/state_machine.py`), НЕ промпт
2. **Tool Planning**: Виконується в коді (`tool_planner.py`) ПЕРЕД викликом LLM
3. **Post-Validation**: Без LLM — code-based перевірка price > 0, photo_url https://
4. **Observability**: Структуровані логи з тегами (state/intent/latency)

## Directory Structure

```
src/
├── agents/           # LangGraph агенти
│   ├── graph.py      # v1 граф (single node)
│   ├── graph_v2.py   # v2 граф (moderation → tools → agent → validation)
│   ├── nodes.py      # Вузли графа
│   └── pydantic_agent.py
├── core/             # Централізована логіка
│   ├── state_machine.py   # FSM, States, Intents, Transitions
│   ├── constants.py       # Backward compatibility aliases
│   ├── models.py          # Pydantic моделі (Product, AgentResponse)
│   ├── input_validator.py # Валідація вхідних metadata
│   ├── product_adapter.py # Унифікація id vs product_id
│   └── tool_planner.py    # Логіка вибору інструментів
├── services/
│   ├── supabase_tools.py  # Supabase інструменти
│   ├── observability.py   # Метрики та логування
│   └── ...
├── integrations/
│   ├── crm/
│   │   ├── order_mapper.py  # CRM контракт
│   │   └── snitkix.py       # Snitkix CRM клієнт
│   └── manychat/
└── conf/
    └── config.py      # Settings з feature flags

data/
├── system_prompt_full.yaml  # Головний промпт (legacy)
├── prompts/                 # LLM-specific prompts
│   ├── base.yaml           # Базовий шаблон
│   ├── grok.yaml           # Grok 4.1 Fast config
│   ├── gpt.yaml            # GPT-5.1 config
│   └── gemini.yaml         # Gemini 3 Pro config
└── domain/
    ├── states.yaml    # Стани FSM
    └── intents.yaml   # Інтенти
```

## State Machine

Єдине джерело правди для станів — `src/core/state_machine.py`.

### States

| State | Description |
|-------|-------------|
| STATE_0_INIT | Початок діалогу |
| STATE_1_DISCOVERY | Пошук товару |
| STATE_2_VISION | Робота з фото |
| STATE_3_SIZE_COLOR | Підбір розміру/кольору |
| STATE_4_OFFER | Пропозиція |
| STATE_5_PAYMENT_DELIVERY | Оплата/Доставка |
| STATE_6_UPSELL | Допродаж |
| STATE_7_END | Завершення |
| STATE_8_COMPLAINT | Скарга (L2) |
| STATE_9_OOD | Поза доменом (L1) |

### Intents

| Intent | Description |
|--------|-------------|
| GREETING_ONLY | Привітання |
| DISCOVERY_OR_QUESTION | Пошук товару |
| PHOTO_IDENT | Фото для ідентифікації |
| SIZE_HELP | Питання про розмір |
| COLOR_HELP | Питання про колір |
| PAYMENT_DELIVERY | Оплата/Доставка |
| COMPLAINT | Скарга |
| THANKYOU_SMALLTALK | Подяка |
| OUT_OF_DOMAIN | Поза доменом |
| UNKNOWN_OR_EMPTY | Невідомо |

## Feature Flags

Налаштування в `src/conf/config.py`:

| Flag | Default | Description |
|------|---------|-------------|
| USE_GRAPH_V2 | False | Багатовузловий граф |
| USE_TOOL_PLANNER | False | Tool planning в коді |
| USE_PRODUCT_VALIDATION | True | Валідація продуктів |
| USE_INPUT_VALIDATION | True | Валідація вхідних metadata |
| ENABLE_OBSERVABILITY | True | Структуроване логування |

## Embeddings

Семантичний пошук використовує:
- **Модель**: `text-embedding-3-large` (1536 dimensions)
- **Fallback**: SHA256 hash-based embedding (для тестів без OpenAI)
- **RPC**: `match_mirt_products(query_embedding, match_count)`

### Дозволені домени для фото

```python
ALLOWED_PHOTO_DOMAINS = (
    "cdn.sitniks.com",
    "sitniks.com",
    "mirt.store",
    "cdn.mirt.store",
)
```

## Product Schema

Канонічне поле — `id` (не `product_id`).

```python
class Product(BaseModel):
    id: int           # Canonical
    name: str
    size: str
    color: str
    price: float      # Must be > 0
    photo_url: str    # Must start with https://
```

## LLM Configuration

```env
LLM_PROVIDER=openrouter          # openrouter, openai, google
LLM_MODEL_GROK=x-ai/grok-4.1-fast
LLM_MODEL_GPT=gpt-5.1
LLM_MODEL_GEMINI=gemini-3-pro
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=2048
```

### Prompt Loader

LLM-specific prompts завантажуються через `src/core/prompt_loader.py`:

```python
from src.core.prompt_loader import load_prompt, get_prompt_for_model

# Load for specific model
grok_config = load_prompt("grok")

# Auto-select based on LLM_PROVIDER config
config = get_prompt_for_model()

# Get formatted system prompt text
text = get_system_prompt_text("gpt")
```

Структура промптів:
- `base.yaml` — спільна частина для всіх LLM
- `{grok,gpt,gemini}.yaml` — LLM-specific overlays (extends base.yaml)

## Rollout Process

1. **Staging**: Enable `USE_GRAPH_V2=true`
2. **Collect metrics**: Monitor `agent_step_latency_ms`, `validation_failures`
3. **Production**: Enable via feature flag
4. **Monitor**: Track escalations, errors
5. **Cleanup**: Remove legacy code after stabilization
