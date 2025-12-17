# MIRT AI Agents — Архітектура та керування

> 📚 **Центральний індекс документації:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

## 1. Загальна ідея

Агентний шар MIRT AI складається з двох рівнів:

- **LangGraph (`src/agents/langgraph`)** — оркестрація, state machine, routing
- **Pydantic AI (`src/agents/pydantic`)** — LLM-агенти, моделі, DI

Потік: `Повідомлення → LangGraph → master_router → Нода → PydanticAI Agent → state update`

---

## 2. LangGraph (`src/agents/langgraph`)

### 2.1. Ключові файли

| Файл | Призначення |
|------|-------------|
| `graph.py` | Production-граф, ноди: moderation, intent, vision, agent, offer, payment, upsell, crm_error, validation, escalation, memory |
| `edges.py` | `master_router`, `route_after_intent`, `route_after_validation` |
| `state.py` | `ConversationState`, `create_initial_state` |
| `state_prompts.py` | Промпти для FSM станів, `determine_next_dialog_phase` |
| `checkpointer.py` | Persistence (Memory/Postgres) |
| `streaming.py` | Streaming токенів |
| `time_travel.py` | Історія, rollback, fork |

### 2.2. Ноди (`langgraph/nodes/`)

| Нода | Призначення |
|------|-------------|
| `agent.py` | Текстовий діалог (`run_support`) |
| `vision.py` | Аналіз фото (`run_vision`) |
| `offer.py` | **Multi-Role Deliberation**, pre/post-validation цін |
| `payment.py` | Збір даних замовлення, HITL interrupt |
| `upsell.py` | Допродаж |
| `escalation.py` | Передача оператору |
| `memory.py` | `memory_context_node`, `memory_update_node` |

---

## 3. Pydantic AI (`src/agents/pydantic`)

### 3.1. Моделі (`models.py`)

- `SupportResponse` — головна модель відповіді
- `VisionResponse` — результат vision
- `PaymentResponse` — дані замовлення
- `OfferDeliberation` — Multi-Role Deliberation (customer/business/quality views)
- `CustomerDataExtracted` — дані клієнта для STATE_5

### 3.2. AgentDeps (`deps.py`)

DI-контейнер:
- `session_id`, `user_id`, `channel`
- `selected_products`, `customer_name`, `customer_phone`
- Сервіси: `db`, `catalog`, `memory`
- Titans-like: `profile`, `facts`, `memory_context_prompt`

Фабрики:
- `create_deps_from_state(state)` — базовий
- `create_deps_with_memory(state)` — з підвантаженням памʼяті

### 3.3. Агенти

| Агент | Файл | Роль |
|-------|------|------|
| Support | `support_agent.py` | Консультант "Софія" |
| Vision | `vision_agent.py` | Розпізнавання фото |
| Payment | `payment_agent.py` | Оформлення замовлень |
| Memory | `memory_agent.py` | Класифікація фактів |

---

## 4. Практичні сценарії

### Змінити поведінку по стейтах
→ `state_prompts.py`, `data/prompts/states/*`

### Додати ноду
→ `nodes/*.py` → `graph.py` → `edges.py`

### Змінити payment flow
→ `state_prompts.py` (payment sub-phases) → `nodes/payment.py`

### Змінити vision
→ `nodes/vision.py` → `pydantic/vision_agent.py` → `data/vision/*`

---

## 5. Потік діалогу

```
1. Вхідне → build_production_graph().invoke()
2. master_router → вибирає ноду по dialog_phase + intent
3. Нода → викликає Pydantic-агента
4. Оновлення state + dialog_phase
5. end → відповідь клієнту
```

---

> Детальний опис: [DEV_SYSTEM_GUIDE.md](DEV_SYSTEM_GUIDE.md)
