# 🩺 Observability Service — Нервова Система

> **Роль:** "Nervous System" (Нервова Система)
> **Відповідальність:** Збір метрик, трасування (Tracing), аудит витрат (Costs) та структурне логування.

Це головний інструмент **діагностики**. Without data, you are just another person with an opinion.
Завдяки цьому модулю ми перетворюємо "чорну скриньку" AI на прозорий механізм.

---

## 🏗️ Структура

```
src/services/observability/
├── __init__.py             # Експорти всіх функцій
├── observability.py        # 🩺 Core: Tracing, Metrics, Logging
├── billing.py              # 💵 Pricing: MODEL_PRICING, calculate_cost()
└── llm_usage_logger.py     # 📊 Best-effort: log_llm_usage_best_effort()
```

---

## ⚠️ ЗАСТЕРЕЖЕННЯ (Safety Warning)


> 🔴 **КРИТИЧНО:** Цей модуль записує дані у таблицю `llm_traces`.
> Відключення або видалення цього модуля призведе до **повної втрати аналітики** та історії витрат.
> Бот продовжить працювати, але ви станете "сліпими" до інцидентів та білінгу.

---

## 🏗️ Архітектура (Deep Dive)

### Діаграма потоку даних

```mermaid
graph TD
    Agent[🤖 AI Agent] -->|Decorators| Wrapper[tracing.py]
    Wrapper -->|Metrics| Obs[🩺 Observability Service]
    
    Obs -->|Async Task| Tracer[AsyncTracingService]
    
    Tracer -->|Try Write| DB_Trace[(Postgres: llm_traces)]
    
    Tracer -- Fallback (If Error) --> DB_Usage[(Postgres: llm_usage)]
    
    Obs -->|track_metric| InMem[MetricsCollector (RAM)]
```

### 1. `AsyncTracingService` (Фоновий запис)
Працює за принципом **Fire and Forget**, щоб не сповільнювати відповідь користувачу.

*   **Logic:**
    1.  Збирає гігантський JSON-пейлод: `input_snapshot` (Prompt), `output_snapshot` (Response), `tokens_in/out`, `cost_usd`.
    2.  Нормалізує `trace_id` (UUID).
    3.  Намагається записати в `llm_traces` (детальна таблиця).
    4.  🔴 **Fallback Protocol:** Якщо запис в `llm_traces` падає (наприклад, через зміну схеми), він автоматично пробує записати спрощену версію в `llm_usage`. **System never loses billing data.**

### 2. `tracing.py` vs `observability.py`
Це поширена плутанина. Ось різниця:

| Модуль | Призначення | Куди пише? |
| :--- | :--- | :--- |
| **`src/services/observability.py`** | **Business Data**. (Скільки грошей? Що відповів? Який був промпт?). | **PostgreSQL** (`llm_traces`) |
| **`src/agents/pydantic/tracing.py`** | **APM / Debugging**. (Скільки мілісекунд зайняла функція? Де stacktrace?). | **Logfire** / Console |

### 3. `MetricsCollector` (In-Memory)
Це оперативна пам'ять метрик.
*   Зберігає останні 10,000 точок в RAM.
*   Дозволяє "на льоту" отримати статистику через `get_metrics_summary()`.
*   *Ідеально для health-check ендпоінтів.*

---

## 🛠️ Основні функції API

### `log_trace(...)`
Головна функція для AI-нод.
```python
await log_trace(
    session_id="123",
    trace_id="abc-uuid",
    node_name="VisionNode",
    status="SUCCESS",
    input_snapshot={"image": "url...", "prompt": "..."},
    output_snapshot={"category": "sneakers", "color": "white"},
    cost_usd=0.002,   # 💵 Money Shot
    latency_ms=450
)
```

### `track_metric(...)`
Для технічних метрик.
```python
track_metric(
    "tool_latency_ms", 
    150, 
    tags={"tool": "vector_search", "status": "ok"}
)
```

### `log_agent_step(...)`
Для читабельності логів в консолі. Перетворює хаос на порядок:
`INFO: agent_step session=123 state=BUY intent=CONFIRM tool_results=3`

---

## 🔗 Інтеграція (Usage Map)

Цей сервіс "пронизує" 30+ файлів. Ось ключові точки:

1.  **Vision Agent:** Логує розпізнавання фото та впевненість (`confidence`).
2.  **Validation Node:** Фіксує помилки вводу (щоб ми знали, де юзери туплять).
3.  **Moderation:** Рахує PII та Prompt Injection спроби.
4.  **Billing:** Прив'язує витрати до конкретних `trace_id`.

Це **SSOT** (Single Source of Truth) для будь-якої телеметрії в проекті.
