# MIRT AI Agents — Архітектура та керування

## 1. Загальна ідея

Агентний шар MIRT AI складається з двох рівнів:

- **LangGraph (`src/agents/langgraph`)**  
  Оркестрація, state machine, routing, ноди (vision / offer / payment / upsell / escalation / validation).

- **Pydantic AI (`src/agents/pydantic`)**  
  «Мозок» LLM-агентів: system-промпти, строгі моделі (OUTPUT_CONTRACT), DI (`AgentDeps`).

Потік повідомлення:

1. Повідомлення користувача потрапляє в **LangGraph-граф**.
2. `master_router` дивиться на `dialog_phase` + intent → вирішує, яку ноду викликати.
3. Нода (наприклад, `agent_node` або `payment_node`) викликає **Pydantic-агента** (`run_support`, `run_payment`, `run_vision`).
4. Відповідь у вигляді моделей (`SupportResponse`, `VisionResponse`, `PaymentResponse`) оновлює `state` + `dialog_phase`.
5. Наступний крок знову проходить через `master_router`.

---

## 2. Карта папки `src/agents`

### 2.1. Корінь `src/agents`

- **`src/agents/__init__.py`**  
  Фасад для всього агентного шару. Реекспортує:
  - LangGraph: `build_production_graph`, `invoke_graph`, `route_after_intent`, `should_retry`, `stream_events`, `stream_tokens` тощо.
  - Pydantic: `AgentDeps`, `SupportResponse`, `VisionResponse`, `run_support`, `run_vision`, `get_payment_agent`.

  **Навіщо:** зручно підключати агентний шар однією точкою входу: `from src.agents import ...`.

---

### 2.2. Пакет `src/agents/langgraph`

#### Верхній рівень

- **`langgraph/graph.py`**  
  - Збирає **production-граф**.
  - Описує ноди: `moderation`, `intent`, `vision`, `agent`, `offer`, `payment`, `upsell`, `escalation`, `validation`, `end`.
  - Підключає маршрути: `master_router`, `route_after_intent`, `route_after_validation`, `route_after_agent`.

  **Куди лізти, якщо хочеш змінити структуру графа** (додати / прибрати ноду, поміняти зв'язки).

- **`langgraph/edges.py`**  
  - `master_router(state)` — головний роутер по `dialog_phase` + intent (включно з `detect_simple_intent` із `state_prompts.py`).
  - `route_after_intent` — вирішує, куди йти після intent-ноди.
  - `route_after_validation` — що робити після валідації (retry / escalation / end).
  - `route_after_agent` — чи завершувати крок (end), чи йти на наступну ноду.

  **Тут живе логіка переходів між нодами FSM.**

- **`langgraph/state.py`**  
  - `ConversationState` — структура всього стану діалогу: повідомлення, `dialog_phase`, товари, дані клієнта, флаги й службова інформація.
  - `create_initial_state`, `get_state_snapshot`.

  **Якщо потрібно додати нове поле в state** (наприклад, додатковий параметр замовлення) — змінюється тут.

- **`langgraph/state_prompts.py`**  
  - **Повні промпти для всіх FSM-станів:** INIT, DISCOVERY, SIZE_COLOR, OFFER, PAYMENT_DELIVERY, UPSELL, COMPLAINT, OUT_OF_DOMAIN та ін.
  - Payment sub-phases: `REQUEST_DATA`, `CONFIRM_DATA`, `SHOW_PAYMENT`, `THANK_YOU`.
  - Функції:
    - `get_state_prompt(...)` — повертає текст інструкцій під конкретний state (+ sub-phase).
    - `determine_next_dialog_phase(...)` — повна логіка зміни `dialog_phase` за поточним станом, intent та контекстом.
    - `detect_simple_intent(text)` — проста детекція intent по ключових словах.

  **Це головне місце, щоб змінювати поведінку по стейтах** (які питання ставити, як рухатись далі).

- **`langgraph/checkpointer.py`**  
  - Описує типи чекпоінтера (`CheckpointerType`).
  - `get_checkpointer`, `get_postgres_checkpointer` — фабрики збереження стану (MemorySaver / Postgres і т.д.).

  **Сюди варто дивитись, якщо підключаєш реальний персистентний чекпоінтер (БД, Redis).**

- **`langgraph/streaming.py`**  
  - `StreamEventType` (NODE_START, NODE_END, TOKEN, ERROR тощо).
  - Функції для стрімінгу подій і токенів із графа назовні.

  **Важливо для UX** — якщо ти хочеш бачити «живий» стрімінг відповіді замість очікування повного тексту.

- **`langgraph/time_travel.py`**  
  - `get_state_history`, `rollback_to_step`, `fork_from_state`.

  **Адмінський / дебажний інструмент:** дає змогу відмотати діалог або створити нову гілку від минулого стану.

- **`langgraph/__init__.py`**  
  - Збирає публічний API для всього `langgraph`-пакета: graph, checkpointer, streaming, should_retry, time_travel тощо.

---

#### Пакет `langgraph/nodes` — ноди графа

- **`nodes/agent.py`**  
  - `agent_node(state, runner)`:
    - витягує останнє повідомлення користувача,
    - збирає `AgentDeps` із `state` через `create_deps_from_state`,
    - інжектить `state_specific_prompt = get_state_prompt(...)` для поточного FSM-стану,
    - викликає `run_support(...)` (Pydantic-агент),
    - оновлює `current_state`, `dialog_phase`, `metadata`, `selected_products`.

  **Це основна LLM-нода текстового діалогу без віжна й платежів.**

- **`nodes/vision.py`**  
  - `vision_node(state, runner)`:
    - викликає `run_vision(...)` (vision-агент на Pydantic),
    - аналізує фото і підбирає товар із embedded catalog,
    - використовує правила розміру та маркерів із data/vision,
    - виставляє `dialog_phase = WAITING_FOR_SIZE` або `VISION_DONE`.

  **Весь флоу роботи з фото ідентифікації — тут.**

- **`nodes/offer.py`**  
  - `offer_node(state, runner)`:
    - будує оферку по вибраних товарах + розміру + кольору,
    - готує текст пропозиції без оплати,
    - переводить діалог у `OFFER_MADE` / `SIZE_COLOR_DONE`.

  **Ключовий крок «Комерційна пропозиція → далі оплата».**

- **`nodes/payment.py`**  
  - `payment_node(state, runner)`:
    - інтегрується з `run_payment(...)` (Pydantic payment agent),
    - управляє суб-фазами оплати: `REQUEST_DATA → CONFIRM_DATA → SHOW_PAYMENT → THANK_YOU`,
    - оновлює `dialog_phase` на `WAITING_FOR_DELIVERY_DATA`, `WAITING_FOR_PAYMENT_METHOD`, `WAITING_FOR_PAYMENT_PROOF`, `UPSELL_OFFERED`, `COMPLETED`,
    - використовує `interrupt()` для обов'язкового **human approval**.

  **Уся логіка збору даних доставки, реквізитів, скрінів оплати та переходу до upsell.**

- **`nodes/upsell.py`**  
  - `upsell_node(state, runner)`:
    - пропонує додаткові товари після успішної оплати,
    - по результату ставить `dialog_phase = COMPLETED`.

  **Допродаж (upsell) після завершення основного замовлення.**

- **`nodes/escalation.py`**  
  - `escalation_node(state, runner)`:
    - готує текст / структуру для передачі діалогу живому оператору,
    - виставляє `dialog_phase = COMPLETED`.

  **Скарги, складні/ризиковані кейси, ручна обробка.**

- **`nodes/moderation.py`**  
  - Нода модерації: фільтрація контенту, перевірка на відповідність політикам.

  **Стартовий gate перед рештою нод, коли потрібна безпека.**

- **`nodes/intent.py`**  
  - `intent_node(state, runner)`:
    - окрема нода для intent detection (discovery / photo / payment / smalltalk / complaint),
    - працює разом із `route_after_intent` для першої розвилки FSM.

  **Перше розгалуження діалогу за типом запиту.**

- **`nodes/validation.py`**  
  - Перевірка коректності товарів / параметрів / даних.
  - `should_retry(state)` — вирішує, чи можна ще раз уточнити, або вже треба ескалювати.

  **Захист від "кривих" даних перед offer/payment.**

- **`nodes/utils.py`**  
  - Утилітні функції для кількох нод (робота з товарами, форматування і т.п.).

---

### 2.3. Пакет `src/agents/pydantic` — Pydantic AI рівень

- **`pydantic/models.py`**  
  - Pydantic-моделі:
    - `SupportResponse`, `VisionResponse`, `PaymentResponse`,
    - `MessageItem`, `ResponseMetadata`,
    - `StateType`, `IntentType`, `EventType`.

  **Це твій строгий OUTPUT_CONTRACT. Будь-яка відповідь агентів має відповідати цим моделям.**

- **`pydantic/deps.py`**  
  - `AgentDeps` — DI-контейнер для Pydantic-агентів:
    - `session_id`, `trace_id`, `user_id`, `channel`, `language`,
    - `selected_products`, `customer_name`, `customer_phone`, `customer_city`, `customer_nova_poshta`,
    - сервіси: `db: OrderService`, `catalog: CatalogService`,
    - `state_specific_prompt: str | None` — детальні інструкції для поточного FSM-стану (інжектить `agent_node`).
  - `create_deps_from_state(state)` — конвертація LangGraph-стану в `AgentDeps`.

  **Якщо потрібно передати в LLM новий контекст/поле — додаєш його в `AgentDeps` + в `create_deps_from_state`.**

- **`pydantic/support_agent.py`**  
  - Побудова PydanticAI-агента для sales/support:
    - `_get_base_prompt()` → бере `system_prompt_full.yaml` з `data/prompts/system`. 
    - `_add_state_context(ctx)` → додає до промпта короткий опис стану сесії: поточний `current_state`, дані клієнта, обрані товари.
    - `_add_state_instructions(ctx)`:
      1. Якщо в `deps.state_specific_prompt` щось є — використовує саме його (інструкції з `state_prompts.py`).
      2. Якщо ні — підтягує промпт із `registry` (`data/prompts/states/*`).
  - `run_support(message, deps)` — основний entrypoint для текстових відповідей.

  **Тут зібрана основна логіка поведінки sales/support-агента.**

- **`pydantic/vision_agent.py`**  
  - `run_vision(message, deps)` — vision-агент:
    - використовує артефакти з `data/vision/*` (rules, tips, markers),
    - жорстко покладається на embedded catalog,
    - повертає структуровану інформацію про знайдений товар.

  **Увесь «розум по фотках» знаходиться тут.**

- **`pydantic/payment_agent.py`**  
  - `get_payment_agent()`, `run_payment(message, deps)`:
    - окремий агент з правилами по оплаті, реквізитами, логікою sub-phases,
    - працює разом із `nodes/payment.py` та `state_prompts.py` (payment частина FSM).

  **Логіка фінальних кроків замовлення й платежу.**

- **`pydantic/observability.py`**  
  - Логування та метрики викликів Pydantic-агентів (durations, errors, usage).

  **Важливо для моніторингу / дебагу в проді.**

- **`pydantic/__init__.py`**  
  - Реекспортує всі моделі, `AgentDeps`, та функції агентів, щоб їх було зручно імпортувати.

---

## 3. Практичні сценарії: де що правити

### 3.1. Змінити поведінку по стейтах (що говорить бот на кожному кроці)

- **Основне місце:** `src/agents/langgraph/state_prompts.py`.
  - Міняєш тексти для INIT / DISCOVERY / SIZE_COLOR / OFFER / PAYMENT / UPSELL / COMPLAINT / OUT_OF_DOMAIN.
  - Там же прописана логіка переходів між `dialog_phase`.

- Додатково можна коригувати тон і правила в:
  - `data/system_prompt_full.yaml` (глобальні правила агента),
  - `data/prompts/states/*` (додаткові state-специфічні промпти),
  - `pydantic/support_agent.py` (як саме додається контекст до системного промпта).

### 3.2. Додати / прибрати ноду в графі

- **Структура графа:** `src/agents/langgraph/graph.py`.
- **Маршрути між нодами:** `src/agents/langgraph/edges.py`.

Кроки:
1. Додати/змінити ноду в `nodes/*.py`.
2. Підключити її в `graph.py`.
3. Оновити `master_router` / `route_after_*` у `edges.py`, якщо змінюється FSM.

### 3.3. Змінити поведінку оплати

- **Бізнес-логіка / тексти оплати:**
  - `state_prompts.py` (payment стейти й sub-phases),
  - `pydantic/payment_agent.py` (як міркує payment-агент).

- **Оркестрація payment-флоу:**
  - `nodes/payment.py` (коли запускати який sub-phase, коли interrupt для людини, коли переходити в upsell).

### 3.4. Змінити поведінку по фото

- `nodes/vision.py` — як візуальний результат інтегрується в state / dialog_phase.
- `pydantic/vision_agent.py` — як LLM аналізує фото, які правила й tips застосовуються.
- `data/vision/*` — артефакти промпта для віжна.

### 3.5. Дебаг і історія діалогу

- `checkpointer.py` — налаштування сховища стану (in-memory / Postgres і т.д.).
- `time_travel.py` — інструменти `get_state_history`, `rollback_to_step`, `fork_from_state`.

---

## 4. Як читати й розуміти потік діалогу

1. **Вхідне повідомлення** → `build_production_graph().invoke(...)`.
2. **`master_router`** дивиться на:
   - `dialog_phase` (збережений у `ConversationState`),
   - intent із `detect_simple_intent` (по тексту),
   - наявність фото (`has_image`).
3. Вибирається нода: `moderation` / `intent` / `vision` / `agent` / `offer` / `payment` / `upsell` / `escalation` / `validation`.
4. Нода викликає відповідного Pydantic-агента (якщо треба), оновлює `state` + `dialog_phase`.
5. Якщо нова `dialog_phase` потребує відповіді користувачу → крок завершується (`end`), і відповідь віддається клієнту.
6. При наступному повідомленні все починається знову з урахуванням оновленого `state`.

Цей файл можна розглядати як "мапу" агентної архітектури MIRT AI, щоб швидко зрозуміти, **де саме** змінювати логіку під свої задачі.
