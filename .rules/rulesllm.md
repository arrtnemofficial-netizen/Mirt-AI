# 🔥 ЗАЛІЗОБЕТОННИЙ КОДЕКС РОЗРОБКИ v4.0

> **⚠️ КРИТИЧНА ІНСТРУКЦІЯ ДЛЯ AI AGENTS ТА РОЗРОБНИКІВ:**
> Цей документ визначає **НЕПОРУШНІ ЗАКОНИ** архітектури проекту MIRT AI.
> **PydanticAI + LangGraph + CRM Integration = Production-Grade Agentic System**
> Будь-яке відхилення від цих правил вважається **КРИТИЧНОЮ ПОМИЛКОЮ**.
>
> 📚 **Центральний індекс документації:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

---

## 0. Про проект (Контекст для AI)

**MIRT AI** — це AI-консультант для магазину дитячого одягу MIRT.
- **Архітектура:** PydanticAI (мозок) + LangGraph (оркестратор) + PostgreSQL Checkpointer + Snitkix CRM
- **Мова спілкування:** Українська
- **Платформи:** Instagram (ManyChat), Telegram
- **LLM:** Grok/GPT/Gemini через OpenRouter
- **База даних:** Supabase (PostgreSQL) + LangGraph Persistence
- **CRM:** Snitkix (async API + webhooks + Celery tasks)
- **Каталог:** ~100 товарів (Embedded Catalog в system_prompt)

**Ключова ціль:** Допомогти клієнту обрати товар → уточнити розмір/колір → довести до покупки → створити замовлення в CRM з повним контролем статусів.

---

## 🏗️ 1. АРХІТЕКТУРА: PydanticAI + LangGraph + CRM Integration

### 1.1. Тришарова архітектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         🎭 LANGGRAPH LAYER                              │
│                    (The Conductor / Оркестратор)                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  src/agents/langgraph/                                            │  │
│  │  ├── graph.py         # Production Graph Builder                  │  │
│  │  ├── state.py         # ConversationState (TypedDict + Reducers)  │  │
│  │  ├── edges.py         # Routing Logic (Smart Decisions)           │  │
│  │  ├── checkpointer.py  # PostgreSQL/Redis Persistence              │  │
│  │  ├── streaming.py     # Real-time Token Streaming                 │  │
│  │  ├── time_travel.py   # State Rollback/Fork                       │  │
│  │  └── nodes/           # 11 Production Nodes                       │  │
│  │      ├── moderation.py   # Content Filter (Gate)                  │  │
│  │      ├── intent.py       # Intent Detection                       │  │
│  │      ├── agent.py        # Main LLM Processing                    │  │
│  │      ├── vision.py       # Photo Recognition                      │  │
│  │      ├── offer.py        # Product Offers                         │  │
│  │      ├── payment.py      # Payment Flow (HITL) + CRM Integration   │  │
│  │      ├── upsell.py       # Cross-sell + CRM Status Display        │  │
│  │      ├── crm_error.py    # CRM Error Recovery (NEW)               │  │
│  │      ├── validation.py   # Self-Correction Loop                   │  │
│  │      └── escalation.py   # Human Handoff                          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         🧠 PYDANTICAI LAYER                             │
│                      (The Brain / Мозок Агентів)                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  src/agents/pydantic/                                             │  │
│  │  ├── deps.py           # AgentDeps (Dependency Injection)         │  │
│  │  ├── models.py         # OUTPUT_CONTRACT Models (Typed!)          │  │
│  │  ├── support_agent.py  # Main Sales Agent "Ольга"                 │  │
│  │  ├── vision_agent.py   # Photo Recognition Specialist             │  │
│  │  ├── payment_agent.py  # Payment Flow Specialist                  │  │
│  │  └── observability.py  # Logfire Integration                      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         🔄 CRM INTEGRATION LAYER                        │
│                    (External Systems / Зовнішні системи)                │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  src/integrations/crm/                                            │  │
│  │  ├── crmservice.py      # High-level CRM Service (NEW)           │  │
│  │  ├── error_handler.py   # CRM Error Recovery (NEW)               │  │
│  │  ├── webhooks.py        # Snitkix Webhook Handlers (NEW)         │  │
│  │  ├── snitkix.py         # Snitkix Async API Client                │  │
│  │  └── database_schema.sql# Supabase CRM Orders Table (NEW)         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2. Production Graph Flow

```
START → moderation → intent ──┬──→ vision ───┬──→ offer → validation ──┬──→ end → END
                              │              │                          │
                              ├──→ agent ────┤                          │
                              │              │                          │
                              ├──→ offer ────┘                          │
                              │                                         │
                              ├──→ payment (HITL) ──┬──→ upsell ────────┤
                              │                    │                   │
                              │                    ├──→ crm_error ──────┤
                              │                    │   ↓               │
                              │                    │ retry/escalate    │
                              │                    └──→ upsell ────────┤
                              │                                         │
                              └──→ escalation ──────────────────────────┘
                                                         ▲
                                              SELF-CORRECTION LOOP
                                        (validation → retry → agent)
```

---

## � 2. CRM INTEGRATION: Snitkix

### 2.1. Архітектура CRM інтеграції

**Компоненти:**
- `crmservice.py` - High-level service з persistence та idempotency
- `error_handler.py` - Error recovery з retry UI та operator escalation  
- `webhooks.py` - FastAPI endpoints для bidirectional sync
- `snitkix.py` - Async HTTP client для Snitkix API
- `database_schema.sql` - Supabase таблиця `crm_orders`

**Flow:** Payment approval → CRM creation (async Celery) → Status webhook → User notification

### 2.2. Критичні налаштування перед продакшеном

```bash
# 1. Environment Variables (REQUIRED)
SNITKIX_ENABLED=true
SNITKIX_API_URL=https://your-snitkix-instance.com/api
SNITKIX_API_KEY=your-api-key-here

# 2. Database Migration (REQUIRED)
# Execute src/integrations/crm/database_schema.sql in Supabase
CREATE TABLE crm_orders (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    external_id TEXT UNIQUE NOT NULL,
    crm_order_id TEXT,
    status TEXT DEFAULT 'pending',
    order_data JSONB,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

# 3. Celery Worker (REQUIRED)
celery -A src.workers.celery_app worker --loglevel=info

# 4. Webhook Registration (REQUIRED)
# Register with Snitkix:
POST /webhooks/snitkix/order-status
POST /webhooks/snitkix/payment  
POST /webhooks/snitkix/inventory
```

### 2.3. Error Handling Strategy

| Error Type | Recovery Action | User Message |
|------------|-----------------|--------------|
| `network_error` | Auto-retry (max 3) | "Проблеми з зв'язком, спробувати ще раз?" |
| `crm_rejected` | User action required | "Перевірте дані замовлення та повторіть" |
| `timeout` | Retry or escalate | "CRM не відповідає, передати оператору?" |
| `rate_limit` | Auto-retry with delay | "Забагато запитів, спробуйте через хвилину" |
| `unknown` | User choice (retry/escalate) | "Помилка CRM, що робити?" |

### 2.4. CRM Status Flow

```python
# Статуси замовлення в CRM:
"pending" → "queued" (Celery task) → "created" (Snitkix) → "confirmed" (webhook)
      ↓
   "failed" → crm_error_node → retry/escalate → "created" або "escalated"
```

### 2.5. CRM Troubleshooting

| Проблема | Симптоми | Рішення |
|----------|----------|---------|
| `SNITKIX_ENABLED=false` | CRM creation skipped, no errors | Set `SNITKIX_ENABLED=true` in env vars |
| Celery worker not running | Tasks stuck in "queued" status | Start: `celery -A src.workers.celery_app worker --loglevel=info` |
| Missing DB table | Database errors on order creation | Run `src/integrations/crm/database_schema.sql` migration |
| Webhook auth failure | 401 errors from Snitkix | Verify `SNITKIX_API_KEY` matches webhook registration |
| Duplicate orders | Same order created multiple times | Check `external_id` generation and idempotency logic |
| CRM API timeout | "timeout" errors in crm_error_node | Increase timeout settings or check network connectivity |

---

## � 3. КРИТИЧНО: ПРАВИЛА ІМПОРТІВ

### 3.1. Правильні імпорти

```python
# ═══════════════════════════════════════════════════════════════════
# ✅ ГОЛОВНИЙ ENTRY POINT - завжди імпортуй з src.agents
# ═══════════════════════════════════════════════════════════════════

from src.agents import (
    # Entry Points
    get_active_graph,           # Production LangGraph
    setup_observability,        # Logfire setup
    
    # PydanticAI Agents
    run_support,                # Main agent runner
    run_vision,                 # Vision agent runner
    run_payment,                # Payment agent runner
    AgentDeps,                  # Dependency injection
    create_deps_from_state,     # State → AgentDeps bridge
    
    # Output Models (OUTPUT_CONTRACT)
    SupportResponse,            # Main response model
    VisionResponse,             # Vision response model
    PaymentResponse,            # Payment response model
    ProductMatch,               # Product from catalog
    MessageItem,                # Message item
    ResponseMetadata,           # Metadata block
    
    # Type Literals
    IntentType,                 # 10 intent types
    StateType,                  # 10 FSM states
    EventType,                  # 5 event types
    
    # LangGraph State
    ConversationState,          # Full state TypedDict
    create_initial_state,       # State factory
    
    # LangGraph Graph
    build_production_graph,     # Graph builder
    get_production_graph,       # Singleton getter
    invoke_graph,               # Simple invocation
    invoke_with_retry,          # With exponential backoff
    
    # Routing
    route_after_intent,         # Intent → Node routing
    route_after_validation,     # Validation → Retry routing
    
    # Streaming
    stream_events,              # Event streaming
    stream_tokens,              # Token streaming
    StreamEventType,            # Event types
    
    # Time Travel
    get_state_history,          # Get all checkpoints
    rollback_to_step,           # Rollback state
    fork_from_state,            # Fork conversation
    
    # Checkpointer
    get_checkpointer,           # Auto-detect checkpointer
    get_postgres_checkpointer,  # PostgreSQL backend
)

# ═══════════════════════════════════════════════════════════════════
# ✅ ПРЯМІ ІМПОРТИ (коли потрібно щось специфічне)
# ═══════════════════════════════════════════════════════════════════

# PydanticAI напряму
from src.agents.pydantic.support_agent import get_support_agent
from src.agents.pydantic.deps import AgentDeps, create_mock_deps
from src.agents.pydantic.models import SupportResponse, ProductMatch

# LangGraph напряму
from src.agents.langgraph.state import ConversationState, create_initial_state
from src.agents.langgraph.graph import build_production_graph
from src.agents.langgraph.nodes import agent_node, vision_node
from src.agents.langgraph.edges import route_after_intent
```

### 3.2. Заборонені імпорти

```python
# ❌ ЗАБОРОНЕНО - ЦІ ФАЙЛИ НЕ ІСНУЮТЬ:
from src.agents.graph import ...           # НЕ ІСНУЄ!
from src.agents.nodes import ...           # НЕ ІСНУЄ!
from src.agents.graph_v2 import ...        # ЗАСТАРІЛО!
from src.agents.pydantic_agent import ...  # ЗАСТАРІЛО!
```

### 3.3. Структура модуля src/agents/

```
src/agents/
├── __init__.py                  # 🌟 Головний експорт (USE THIS!)
│
├── pydantic/                    # 🧠 THE BRAIN
│   ├── __init__.py              # Експорт PydanticAI API
│   ├── deps.py                  # AgentDeps (DI Container)
│   ├── models.py                # OUTPUT_CONTRACT Models
│   ├── support_agent.py         # Agent "Ольга" (main)
│   ├── vision_agent.py          # Vision specialist
│   ├── payment_agent.py         # Payment specialist
│   └── observability.py         # Logfire integration
│
└── langgraph/                   # 🎭 THE CONDUCTOR
    ├── __init__.py              # Експорт LangGraph API
    ├── state.py                 # ConversationState + Reducers
    ├── graph.py                 # Production Graph Builder
    ├── edges.py                 # Routing Logic
    ├── checkpointer.py          # PostgreSQL/Redis Persistence
    ├── streaming.py             # Real-time Streaming
    ├── time_travel.py           # Rollback/Fork
    └── nodes/                   # 🔧 Individual Nodes
        ├── __init__.py          # Node exports
        ├── moderation.py        # Content filtering
        ├── intent.py            # Intent detection
        ├── agent.py             # Main LLM node
        ├── vision.py            # Photo recognition
        ├── offer.py             # Product offers
        ├── payment.py           # Payment (HITL)
        ├── upsell.py            # Cross-sell
        ├── crm_error.py         # CRM Error Recovery (NEW)
        ├── validation.py        # Self-correction
        ├── escalation.py        # Human handoff
        └── utils.py             # Shared utilities
```

---

## 🎯 4. PydanticAI ПРАВИЛА

### 4.1. AgentDeps (Dependency Injection)

```python
# ✅ ПРАВИЛЬНО: Використовуй AgentDeps для всіх залежностей
from src.agents import AgentDeps, create_deps_from_state

# Створення з LangGraph state
deps = create_deps_from_state(langgraph_state)

# Або вручну
deps = AgentDeps(
    session_id="sess_123",
    user_id="user_456",
    current_state="STATE_1_DISCOVERY",
    channel="instagram",
    has_image=False,
    selected_products=[...],
    customer_name="Марія",
)

# Виклик агента
response = await run_support("Привіт!", deps)
```

### 4.2. Structured Output (OUTPUT_CONTRACT)

```python
# PydanticAI ЗАВЖДИ повертає типізовану відповідь!
from src.agents import SupportResponse

response: SupportResponse = await run_support(message, deps)

# Доступ до полів
print(response.event)                    # "simple_answer" | "clarifying_question" | ...
print(response.messages[0].content)      # Текст відповіді
print(response.products[0].name)         # Товар з каталогу
print(response.metadata.current_state)   # "STATE_4_OFFER"
print(response.metadata.intent)          # "SIZE_HELP"
print(response.escalation)               # EscalationInfo | None
```

### 4.3. OUTPUT_CONTRACT Models (актуальна схема)

```python
class SupportResponse(BaseModel):
    """Головна модель відповіді агента (OUTPUT_CONTRACT)."""
    
    # REQUIRED
    event: EventType                 # "simple_answer" | "clarifying_question" | ...
    messages: list[MessageItem]      # [{type: "text", content: "..."}], min_length=1
    metadata: ResponseMetadata       # {session_id, current_state, intent, escalation_level}

    # OPTIONAL (можуть бути порожні)
    products: list[ProductMatch] = Field(
        default_factory=list,
        description="Товари ТІЛЬКИ з CATALOG (id, name, price, size, color, photo_url)",
    )
    reasoning: str | None = Field(
        default=None,
        description="Internal debug log (Input -> Intent -> Catalog -> State -> Output)",
    )
    escalation: EscalationInfo | None = Field(
        default=None,
        description="Required if event='escalation'",
    )
    customer_data: CustomerDataExtracted | None = Field(
        default=None,
        description="Дані клієнта з повідомлення (для STATE_5)",
    )
    deliberation: OfferDeliberation | None = Field(
        default=None,
        description="Multi-role analysis: customer/business/quality views (для STATE_4_OFFER)",
    )


class ProductMatch(BaseModel):
    """Товар з CATALOG - relaxed валідація (Vision-friendly)."""

    # name обовʼязковий, інші поля можуть бути заповнені пізніше з БД
    id: int = Field(
        default=0,
        description="Product ID (0 якщо невідомий, шукаємо по name в CATALOG)",
    )
    name: str = Field(description="Назва товару точно як в CATALOG")
    price: float = Field(
        default=0.0,
        ge=0,
        description="Ціна в грн (0 = варіативна, дізнатись з DB)",
    )
    size: str | None = Field(default=None, description="Розмір (якщо клієнт вказав)")
    color: str = Field(default="", description="Колір (може бути порожнім)")
    photo_url: str = Field(
        default="",
        description="URL фото з CATALOG (може бути порожнім)",
    )

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("photo_url MUST start with 'https://'")
        return v
```

### 4.4. Dynamic System Prompts

```python
# PydanticAI підтримує динамічні промпти через функції
@agent.system_prompt
async def add_state_context(ctx: RunContext[AgentDeps]) -> str:
    """Додає контекст сесії до промпта."""
    deps = ctx.deps
    return f"""
    --- КОНТЕКСТ ---
    Session: {deps.session_id}
    State: {deps.current_state}
    Products: {len(deps.selected_products)}
    """

# Реєстрація tools
@agent.tool
async def get_size_recommendation(ctx: RunContext[AgentDeps], height_cm: int) -> str:
    """Рекомендація розміру за зростом."""
    ...
```

### 4.5. Agent Creation (PydanticAI 1.23+)

```python
# ⚠️ ВАЖЛИВО: PydanticAI 1.23+ API Changes
# - result_type → output_type (в конструкторі Agent)
# - result.output залишається (НЕ result.response!)

from pydantic_ai import Agent

# ✅ ПРАВИЛЬНО (PydanticAI 1.23+)
agent = Agent(
    model,
    deps_type=AgentDeps,
    output_type=SupportResponse,  # НЕ result_type!
    system_prompt="...",
    retries=2,
)

# Виклик агента
result = await agent.run(message, deps=deps)
response = result.output  # НЕ result.response (це ModelResponse)!

# ❌ ЗАСТАРІЛО (PydanticAI < 1.23)
# result_type=SupportResponse  # Помилка: Unknown keyword arguments
```

### 4.6. Memory-Aware AgentDeps (Titans-like памʼять)

```python
from src.agents.pydantic.deps import create_deps_with_memory

# LangGraph state → AgentDeps + memory context
deps = await create_deps_with_memory(state)

# Усередині:
# - Завантажуються профіль (Persistent Memory)
# - Останні факти (Fluid Memory)
# - Формується memory_context_prompt для system prompt
```

---

## 🌊 5. LangGraph ПРАВИЛА

### 5.1. ConversationState (TypedDict + Reducers)

```python
from src.agents import ConversationState, create_initial_state

# Створення initial state
state = create_initial_state(
    session_id="sess_123",
    messages=[{"role": "user", "content": "Привіт!"}],
    metadata={"channel": "instagram", "user_id": "user_456"},
)

# State fields з proper reducers
class ConversationState(TypedDict, total=False):
    # Core
    messages: Annotated[list, add_messages]      # LangGraph message reducer
    current_state: str                           # FSM state
    metadata: Annotated[dict, merge_dict]        # Merging metadata
    
    # Session
    session_id: str
    thread_id: str                               # LangGraph persistence key
    
    # Intent & Routing
    detected_intent: str | None
    has_image: bool
    image_url: str | None
    
    # Products
    selected_products: list[dict]
    offered_products: list[dict]
    
    # Moderation & Escalation
    should_escalate: bool
    escalation_reason: str | None
    
    # Self-Correction Loop
    validation_errors: list[str]
    retry_count: int
    max_retries: int                             # Default: 3
    
    # Human-in-the-Loop
    awaiting_human_approval: bool
    approval_type: Literal["payment", "refund", "discount", None]
    human_approved: bool | None
    
    # PydanticAI Output
    agent_response: Annotated[dict, replace_value]  # Latest structured response
    
    # Time Travel
    step_number: int
```

### 5.2. Graph Invocation

```python
from src.agents import get_active_graph, invoke_graph, invoke_with_retry

# Простий виклик
graph = get_active_graph()
result = await graph.ainvoke(
    state,
    config={"configurable": {"thread_id": session_id}}
)

# Через helper (рекомендовано)
result = await invoke_graph(
    session_id=session_id,
    messages=[{"role": "user", "content": message}],
    metadata={"channel": "instagram"},
)

# З retry logic
result = await invoke_with_retry(
    state=state,
    session_id=session_id,
    max_attempts=3,  # Exponential backoff
)
```

### 5.3. Human-in-the-Loop (HITL)

```python
from src.agents.langgraph.graph import resume_after_interrupt

# Graph pauses before payment node (interrupt_before=["payment"])
# Manager reviews and approves/rejects

# Resume with human decision
result = await resume_after_interrupt(
    session_id=session_id,
    response=True,  # Approved / False = Rejected
)
```

### 5.4. Time Travel

```python
from src.agents import get_state_history, rollback_to_step, fork_from_state

# Get all checkpoints for session
history = await get_state_history(graph, session_id)
for checkpoint in history:
    print(f"Step {checkpoint.step_number}: {checkpoint.current_state}")

# Rollback to specific step
result = await rollback_to_step(graph, session_id, step_number=5)

# Fork conversation (for A/B testing)
new_session_id = await fork_from_state(graph, session_id, step_number=3)
```

### 5.5. Streaming

```python
from src.agents import stream_events, stream_tokens, StreamEventType

# Stream all events
async for event in stream_events(graph, state, session_id):
    if event.type == StreamEventType.NODE_START:
        print(f"Starting node: {event.node}")
    elif event.type == StreamEventType.TOKEN:
        print(event.token, end="", flush=True)

# Stream only tokens
async for token in stream_tokens(graph, state, session_id):
    print(token, end="", flush=True)
```

---

## 🔀 6. ROUTING LOGIC

### 6.1. Intent-Based Routing

```python
# src/agents/langgraph/edges.py

def route_after_intent(state: dict) -> IntentRoute:
    """Route based on detected intent."""
    intent = state.get("detected_intent")
    current_state = state.get("current_state")
    
    # Direct mappings
    if intent == "PHOTO_IDENT":
        return "vision"
    if intent == "COMPLAINT":
        return "escalation"
    
    # Context-aware routing
    if intent == "PAYMENT_DELIVERY":
        if current_state in ["STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY"]:
            return "payment"
        if state.get("selected_products"):
            return "offer"
    
    return "agent"  # Default
```

### 6.2. Self-Correction Loop

```python
def route_after_validation(state: dict) -> ValidationRoute:
    """Enable self-correction loop."""
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    
    if not errors:
        return "end"           # Success!
    
    if retry_count >= max_retries:
        return "escalation"    # Give up, call human
    
    return "agent"             # Retry with feedback
```

---

## 📦 7. OUTPUT_CONTRACT (Pydantic Models)

### 7.1. Event Types (5)

| Event | Опис | Коли використовувати |
|-------|------|---------------------|
| `simple_answer` | Пряма відповідь | Звичайне питання |
| `clarifying_question` | Уточнення | Потрібна інформація |
| `multi_option` | Варіанти вибору | 2+ товари підходять |
| `escalation` | Передача менеджеру | Скарга, складне питання |
| `end_smalltalk` | Завершення | Прощання, подяка |

### 7.2. Intent Types (10)

| Intent | Опис | → Node |
|--------|------|--------|
| `GREETING_ONLY` | Просте привітання | agent |
| `DISCOVERY_OR_QUESTION` | Пошук товару | agent |
| `PHOTO_IDENT` | Ідентифікація фото | vision |
| `SIZE_HELP` | Допомога з розміром | agent/offer |
| `COLOR_HELP` | Допомога з кольором | agent/offer |
| `PAYMENT_DELIVERY` | Оплата/доставка | payment |
| `COMPLAINT` | Скарга | escalation |
| `THANKYOU_SMALLTALK` | Подяка | agent |
| `OUT_OF_DOMAIN` | Не по темі | agent |
| `UNKNOWN_OR_EMPTY` | Незрозуміло | agent |

### 7.3. State Types (11)

| State | Опис | Transitions |
|-------|------|-------------|
| `STATE_0_INIT` | Початок розмови | → DISCOVERY |
| `STATE_1_DISCOVERY` | Пошук товару | → VISION/SIZE_COLOR/OFFER |
| `STATE_2_VISION` | Аналіз фото | → OFFER |
| `STATE_3_SIZE_COLOR` | Підбір розміру | → OFFER |
| `STATE_4_OFFER` | Конкретна пропозиція | → PAYMENT/UPSELL |
| `STATE_5_PAYMENT_DELIVERY` | Оформлення | → END |
| `STATE_6_UPSELL` | Cross-sell | → PAYMENT/END |
| `STATE_7_END` | Завершення | Terminal |
| `STATE_8_COMPLAINT` | Скарга | → ESCALATION |
| `STATE_9_OOD` | Out of domain | → DISCOVERY |
| `CRM_ERROR_HANDLING` | CRM помилка | → CRM_ERROR/RETRY/ESCALATE |

---

## 🏛️ 8. SSOT (Single Source of Truth)

| Що | Де визначено | ЗАБОРОНЕНО |
|----|--------------|------------|
| **States** | `src/core/state_machine.py` | Вигадувати стани |
| **Intents** | `src/agents/pydantic/models.py` | Дублювати enum |
| **Events** | `src/agents/pydantic/models.py` | Додавати без узгодження |
| **OUTPUT_CONTRACT** | `src/agents/pydantic/models.py` | Змінювати структуру |
| **AgentDeps** | `src/agents/pydantic/deps.py` | Дублювати DI logic |
| **ConversationState** | `src/agents/langgraph/state.py` | Дублювати state |
| **Routing** | `src/agents/langgraph/edges.py` | Хардкодити маршрути |
| **Каталог** | `data/system_prompt_full.yaml` | Зберігати в коді |
| **Конфігурація** | `src/conf/config.py` | Хардкодити API ключі |
| **CRM Integration** | `src/integrations/crm/` | Ігнорувати ідемпотентність |

---

## 🔧 9. NODES (11 Production Nodes)

### 9.1. Node Contract

```python
async def node_name(state: dict[str, Any]) -> dict[str, Any]:
    """
    Every node MUST:
    1. Accept state dict
    2. Return partial state update (only changed fields)
    3. Handle errors gracefully (return error state)
    4. Log operations for observability
    """
    try:
        # Process...
        return {
            "current_state": "STATE_X",
            "step_number": state.get("step_number", 0) + 1,
        }
    except Exception as e:
        logger.error("Node failed: %s", e)
        return {
            "last_error": str(e),
            "retry_count": state.get("retry_count", 0) + 1,
        }
```

### 9.2. Node → PydanticAI Integration

```python
# src/agents/langgraph/nodes/agent.py

async def agent_node(state: dict, runner=None) -> dict:
    """Main agent node using PydanticAI."""
    
    # 1. Create deps from state (DI bridge)
    deps = create_deps_from_state(state)
    
    # 2. Extract user message
    user_message = extract_user_message(state.get("messages", []))
    
    # 3. Call PydanticAI agent
    response: SupportResponse = await run_support(
        message=user_message,
        deps=deps,
    )
    
    # 4. Return structured state update
    return {
        "current_state": response.metadata.current_state,
        "detected_intent": response.metadata.intent,
        "messages": [{"role": "assistant", "content": str(response)}],
        "agent_response": response.model_dump(),  # Full structured output
        "selected_products": [p.model_dump() for p in response.products],
        "should_escalate": response.event == "escalation",
    }
```

---

## 🗄️ 10. PERSISTENCE & CHECKPOINTING

### 10.1. PostgreSQL Checkpointer

```python
from src.agents import get_checkpointer, get_postgres_checkpointer

# Auto-detect (uses POSTGRES_URI from env)
checkpointer = get_checkpointer()

# Explicit PostgreSQL
checkpointer = get_postgres_checkpointer(
    uri=settings.POSTGRES_URI,
)

# Build graph with checkpointer
graph = build_production_graph(
    runner=default_runner,
    checkpointer=checkpointer,
)
```

### 10.2. What's Persisted?

| Що | Де | Навіщо |
|----|-----|--------|
| ConversationState | PostgreSQL `checkpoints` | Відновлення після рестарту |
| Message History | `messages` field + `mirt_messages` | Контекст розмови |
| Selected Products | `selected_products` field | Кошик |
| Customer Data | `metadata.customer_*` | CRM |

---

## 📊 11. OBSERVABILITY (Logfire)

```python
from src.agents import setup_observability

# Setup at app start
setup_observability(
    service_name="mirt-ai",
    environment="production",
)

# PydanticAI автоматично логує:
# - Agent calls with deps
# - Tool usage
# - Response validation
# - Retries

# LangGraph логує:
# - Node execution
# - State transitions
# - Checkpointing
```

---

## ✅ 12. ЧЕКЛІСТ ПЕРЕД КОМІТОМ

| # | Перевірка | Що робити |
|---|-----------|-----------|
| 1 | Імпортую з `src.agents`? | ✅ Так, використовуй головний entry point |
| 2 | Використовую `AgentDeps`? | ✅ Ніяких глобальних змінних |
| 3 | Повертаю типізовану відповідь? | ✅ SupportResponse/VisionResponse |
| 4 | Node повертає partial update? | ✅ Тільки змінені поля |
| 5 | Обробляю помилки? | ✅ try/except + logger.error |
| 6 | Є тест? | ✅ pytest з моками |
| 7 | Промпт синхронізований? | ✅ States/Intents в моделях |

---

## 🚫 13. ЗАБОРОНЕНІ ДІЇ

| # | ЗАБОРОНЕНО | Чому |
|---|------------|------|
| 1 | Імпортувати з `src.agents.graph` | Не існує |
| 2 | Викликати LLM напряму | Використовуй PydanticAI agents |
| 3 | Створювати state вручну | Використовуй `create_initial_state` |
| 4 | Модифікувати state мутабельно | LangGraph reducers! |
| 5 | Ігнорувати `retry_count` | Self-correction loop |
| 6 | Хардкодити routing | Використовуй edges.py |
| 7 | Пропускати `thread_id` | Ламає persistence |
| 8 | `except: pass` | Ховає помилки |
| 9 | Змінювати OUTPUT_CONTRACT | Зламає парсинг |
| 10 | Видаляти тести | Маскує баги |
| 11 | Блокувати payment на CRM | CRM - async, не блокуй потік |
| 12 | Ігнорувати ідемпотентність | Дублікати в CRM |

---

## 🔄 14. ТИПОВІ PATTERNS

### 14.1. Webhook Handler

```python
@router.post("/webhooks/manychat")
async def manychat_webhook(request: ManyChatRequest):
    # 1. Create state
    state = create_initial_state(
        session_id=request.subscriber_id,
        messages=[{"role": "user", "content": request.message}],
        metadata={
            "channel": "instagram",
            "user_id": request.subscriber_id,
        },
    )
    
    # 2. Invoke graph
    result = await invoke_graph(state=state, session_id=request.subscriber_id)
    
    # 3. Extract response from agent_response
    agent_response = result.get("agent_response", {})
    reply_text = agent_response.get("messages", [{}])[0].get("content", "")
    
    return {"reply": reply_text}
```

### 14.2. Testing Pattern

```python
@pytest.fixture
def mock_deps():
    return create_mock_deps(session_id="test_session")

@pytest.mark.asyncio
async def test_support_agent(mock_deps, mock_llm):
    with patch("src.agents.pydantic.support_agent._get_model", return_value=mock_llm):
        response = await run_support("Привіт!", mock_deps)
        
        assert response.event in ["simple_answer", "clarifying_question"]
        assert len(response.messages) > 0
        assert response.metadata.session_id == "test_session"
```

---

## 🎯 15. QUICK REFERENCE

```python
# === ENTRY POINTS ===
from src.agents import get_active_graph, run_support, run_vision

# === MODELS ===
from src.agents import SupportResponse, ProductMatch, AgentDeps

# === STATE ===
from src.agents import ConversationState, create_initial_state

# === INVOCATION ===
result = await invoke_graph(session_id="...", messages=[...])

# === STREAMING ===
async for token in stream_tokens(graph, state, session_id):
    print(token, end="")

# === TIME TRAVEL ===
await rollback_to_step(graph, session_id, step_number=5)
```

---

> **🔥 ФІНАЛЬНЕ СЛОВО:**
> 
> Ця архітектура — **Production-Grade Agentic System**.
> PydanticAI дає нам type-safe agents з DI.
> LangGraph дає нам persistence, routing, HITL.
> Разом вони — непереможна комбінація.
> 
> **Пиши код так, ніби його буде підтримувати маніяк з доступом до твого production.**
> 
> **Якщо сумніваєшся — запитай. Якщо не знаєш — не вигадуй.**
