---
name: Hard
overview: ""
todos: []
---

# Production hardening plan (architecture on shelves)

## Внутрішній Аналіз (Ukrainian)

Реальна проблема: у `src/` є **архітектурні місця, які працюють “поки пощастить”**, але в проді дадуть інциденти: sync DB в async endpoints, `asyncio.run()` усередині сервісів, відсутність TTL‑фільтра для memory фактів (TTL “не працює” без cleanup), і неконсистентні lifecycle/DI підходи. Є 3 шляхи: A) швидкі обгортки (`to_thread`) і латки, B) системна стандартизація async‑шляху на `AsyncConnectionPool`, C) “великий rewrite”. Обираю **B з точковими кроками**, бо це мінімізує ризик і дає перевірювану надійність.

## План Виконання

### ЗАДАЧА 1: Додати safety‑rail тести для реальних прод‑кейсів (першим кроком)

- **Чому саме так**: зараз route snapshot + unit тести не ловлять критичні runtime‑помилки в ManyChat push mode (dedupe), TTL‑семантику memory, та блокування в async.

- **Ризик**: тести можуть бути “крихкі”, якщо перевірятимуть внутрішні деталі.

- **Як перевірю**: тести мають бути стабільні, швидкі, без мережі; повинні падати при поверненні `asyncio.run()` у web‑код і при зникненні TTL‑фільтра.

**Додати тести (нові):**

- `tests/test_manychat_dedupe_path.py`:

- перевірити, що webhook з `message_id` не падає (нема `TypeError` у ctor), і викликає dedupe.

- перевірити, що dedupe не використовує `asyncio.run()` в async‑контексті.

- `tests/test_memory_ttl_enforced.py`:

- перевірити, що `get_facts()` не повертає факти з `expires_at < NOW()`.

- `tests/test_health_async_db.py` (smoke):

- перевірити, що health endpoints використовують async pool (або принаймні не викликають sync connect).

### ЗАДАЧА 2: Виправити ManyChat webhook dedupe (критичний баг)

- **Чому саме так**: у `src/server/routers/webhooks_manychat.py` створення `WebhookDedupeStore(db=..., use_postgres=...)` не відповідає реальному `__init__` класу → прод‑падіння при наявності `message_id`.

- **Ризик**: зміна dedupe може вплинути на ідемпотентність (дублікати почнуть проходити).

- **Як перевірю**: нові тести + ручний виклик endpoint у dev з фейковим `message_id` + логування “duplicate ignored”.

**Зміни (файли):**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)

- зробити API явним: `async def check_and_mark_async(...)` для FastAPI.

- залишити sync‑wrapper **тільки** для sync контексту (workers/CLI), без `asyncio.run()` всередині web‑коду.

- [`src/server/routers/webhooks_manychat.py`](src/server/routers/webhooks_manychat.py)

- викликати `await dedupe_store.check_and_mark_async(...)`.

- прибрати/виправити зайві параметри конструктора (привести до реальної сигнатури).

### ЗАДАЧА 3: “Залізобетонний” TTL для memory без cron/infra

- **Чому саме так**: зараз `mirt_memories` читаються як `is_active=TRUE`, але **expires_at не фільтрується**. Якщо cleanup не запускається, TTL фактично не працює.

- **Ризик**: можна випадково “вимкнути” корисні факти, якщо помилково виставляються `expires_at`.

- **Як перевірю**: unit/integration тест, що expired факти не повертаються; додатково лог/метрика скільки fact’ів відфільтровано.

**Зміни (файли):**

- [`src/services/memory/facts.py`](src/services/memory/facts.py)

- у `get_facts()` додати SQL‑фільтр: `AND (expires_at IS NULL OR expires_at > NOW())`.

- аналогічно у `search_facts()` (і будь‑яких інших “read” методах).

---

### ЗАДАЧА 4: Стандартизувати Postgres доступ у FastAPI на async pool (без блокування event loop)

- **Чому саме так**: у `src/server/routers/health.py` є `with psycopg.connect(...)` всередині `async def` → це блокує event loop і під навантаженням дає таймаути/деградацію. Ти вже обрав підхід **async‑pool‑everywhere**.

- **Ризик**: неправильний lifecycle пулу (не `open/close`), витоки конекшенів, або “pool not opened” у рантаймі.

- **Як перевірю**:

    - unit smoke: health endpoints не імпортують/не викликають sync connect

    - інтеграційно: `/health/*` під навантаженням тримає p95 без стрибків

    - метрика: кількість активних конекшенів/помилки pool

**Зміни (файли):**

- [`src/services/storage/postgres_pool.py`](src/services/storage/postgres_pool.py)

    - зробити пул керованим через lifespan: створення + `await pool.open()` + `await pool.close()`

    - явно фіксувати таймаути/параметри пулу

- [`src/server/main.py`](src/server/main.py)

    - у `lifespan` ініціалізувати Postgres pool на старті (і закривати на shutdown)

- [`src/server/routers/health.py`](src/server/routers/health.py)

    - замінити `psycopg.connect(...)` на `await get_postgres_pool(); async with pool.connection() ...`

**Decision tree (коли що робити):**

- Якщо `CELERY_ENABLED=true` і Redis доступний → health може також показувати стан worker’ів як зараз.

- Якщо `DATABASE_URL` відсутній → health повертає degraded/disabled без падіння.

---

### ЗАДАЧА 5: Прибрати `asyncio.run()` з web‑шляху (гарантія “не впаде в уже запущеному loop”)

- **Чому саме так**: `WebhookDedupeStore.check_and_mark()` зараз робить `asyncio.run(...)`. Це працює “поки пощастить”, але може впасти у проді, якщо буде викликано з async контексту (FastAPI).

- **Ризик**: зламати dedupe семантику → дублікати почнуть проходити або будуть false positives.

- **Як перевірю**:

    - тест, який викликає ManyChat webhook push mode з `message_id` і не отримує 500

    - тест, який гарантує: в async контексті викликається тільки async API (`await ...`)

**Зміни (файли):**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)

    - зробити **два** явних API:

        - `async def check_and_mark_async(...) -> bool` (для FastAPI)

        - `def check_and_mark(...) -> bool` (sync wrapper тільки для sync контекстів; без `asyncio.run` у web)

    - так само для cleanup: `cleanup_expired_async` + sync wrapper

- [`src/server/routers/webhooks_manychat.py`](src/server/routers/webhooks_manychat.py)

    - у push mode замінити виклик на `await dedupe_store.check_and_mark_async(...)`

---

### ЗАДАЧА 6: “Покласти по поличках” lifecycle HTTP клієнтів (Sitniks/ManyChat) + timeouts/retries

- **Чому саме так**: `httpx.AsyncClient` створюється у Sitniks на кожен виклик. Це зайвий overhead і немає централізованої політики таймаутів/ретраїв/логів.

- **Ризик**: неправильне reuse клієнта (не закрили), або глобальний клієнт без timeout → зависання.

- **Як перевірю**:

    - unit: клієнт створюється 1 раз на процес і закривається на shutdown

    - інтеграційно: під навантаженням немає вибуху TCP конектів

**Зміни (файли):**

- [`src/server/main.py`](src/server/main.py)

    - створити shared `httpx.AsyncClient` в lifespan (один для зовнішніх сервісів)

- [`src/integrations/crm/sitniks_chat_service.py`](src/integrations/crm/sitniks_chat_service.py)

    - інʼєктити клієнт або брати через фабрику/DI (без `async with AsyncClient` у кожному методі)

- [`src/integrations/manychat/api_client.py`](src/integrations/manychat/api_client.py)

    - переконатися, що клієнт закривається (вже є `close()`), підʼєднати до shutdown

---

### ЗАДАЧА 7: Maintenance без cron/infra (реалістично “працює зараз”)

- **Чому саме так**: ти сказав “у мене поки нічого немає” (без cron). Але таблиці `webhook_dedupe` і `mirt_memories` можуть рости.

- **Ризик**: якщо робити cleanup занадто часто → зайве навантаження на БД.

- **Як перевірю**:

    - метрика: кількість rows у `webhook_dedupe` і `mirt_memories` стабілізується

    - немає сплесків latency під час cleanup

**Рішення (decision tree):**

- Якщо ми реалізували **TTL‑фільтр на читанні** (ЗАДАЧА 3) → memory cleanup стає “опційним” (це тільки гігієна БД).

- Для `webhook_dedupe` (ідемпотентність) cleanup також опційний для логіки, але потрібний для розміру таблиці.

**Варіанти реалізації без cron (обрати один):**

A) **Опортуністичний cleanup всередині існуючих Celery задач** (рекомендовано, якщо `CELERY_ENABLED=true`):

- раз на N запусків `summarization-check-1h` або `followups-check-15min` виконувати:

    - `WebhookDedupeStore.cleanup_expired_async()` (або SQL delete)

    - `MemoryService.cleanup_expired()` (якщо memory увімкнено)

B) **Опортуністичний cleanup у web‑процесі** (якщо Celery нема):

- у ManyChat webhook (push mode) раз на N запитів запускати `cleanup_expired_async()` в background (не блокуючи response)

C) **Вимкнути cleanup до появи cron**:

- приймаємо ріст таблиць, але система працює; паралельно плануємо cron пізніше.

**Файли:**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)

- [`src/workers/tasks/summarization.py`](src/workers/tasks/summarization.py) або [`src/workers/tasks/followups.py`](src/workers/tasks/followups.py)

- (опційно) [`docs/deployment/MEMORY_CLEANUP.md`](docs/deployment/MEMORY_CLEANUP.md) — уже є

---

## Додатковий “червоний прапорець” (внести в backlog)

### FOLLOWUPS night-mode + “кракозябри”

- У `src/workers/tasks/followups.py` є fallback рядок з `????????...` (кодування/хардкод).

- Якщо стратегія продукту: “пишемо клієнту в будь-який час” → night-mode треба прибрати або зробити нормальний текст через snippet/env.

- аналогічно у `search_facts()` (і будь‑яких інших “read” методах).

---

### ЗАДАЧА 4: Стандартизувати Postgres доступ у FastAPI на async pool (без блокування event loop)

- **Чому саме так**: у `src/server/routers/health.py` є `with psycopg.connect(...)` всередині `async def` → це блокує event loop і під навантаженням дає таймаути/деградацію. Ти вже обрав підхід **async‑pool‑everywhere**.
- **Ризик**: неправильний lifecycle пулу (не `open/close`), витоки конекшенів, або “pool not opened” у рантаймі.
- **Як перевірю**:
        - unit smoke: health endpoints не імпортують/не викликають sync connect
        - інтеграційно: `/health/*` під навантаженням тримає p95 без стрибків
        - метрика: кількість активних конекшенів/помилки pool

**Зміни (файли):**

- [`src/services/storage/postgres_pool.py`](src/services/storage/postgres_pool.py)
        - зробити пул керованим через lifespan: створення + `await pool.open()` + `await pool.close()`
        - явно фіксувати таймаути/параметри пулу
- [`src/server/main.py`](src/server/main.py)
        - у `lifespan` ініціалізувати Postgres pool на старті (і закривати на shutdown)
- [`src/server/routers/health.py`](src/server/routers/health.py)
        - замінити `psycopg.connect(...)` на `await get_postgres_pool(); async with pool.connection() ...`

**Decision tree (коли що робити):**

- Якщо `CELERY_ENABLED=true` і Redis доступний → health може також показувати стан worker’ів як зараз.
- Якщо `DATABASE_URL` відсутній → health повертає degraded/disabled без падіння.

---

### ЗАДАЧА 5: Прибрати `asyncio.run()` з web‑шляху (гарантія “не впаде в уже запущеному loop”)

- **Чому саме так**: `WebhookDedupeStore.check_and_mark()` зараз робить `asyncio.run(...)`. Це працює “поки пощастить”, але може впасти у проді, якщо буде викликано з async контексту (FastAPI).
- **Ризик**: зламати dedupe семантику → дублікати почнуть проходити або будуть false positives.
- **Як перевірю**:
        - тест, який викликає ManyChat webhook push mode з `message_id` і не отримує 500
        - тест, який гарантує: в async контексті викликається тільки async API (`await ...`)

**Зміни (файли):**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)
        - зробити **два** явних API:
                - `async def check_and_mark_async(...) -> bool` (для FastAPI)
                - `def check_and_mark(...) -> bool` (sync wrapper тільки для sync контекстів; без `asyncio.run` у web)
        - так само для cleanup: `cleanup_expired_async` + sync wrapper
- [`src/server/routers/webhooks_manychat.py`](src/server/routers/webhooks_manychat.py)
        - у push mode замінити виклик на `await dedupe_store.check_and_mark_async(...)`

---

### ЗАДАЧА 6: “Покласти по поличках” lifecycle HTTP клієнтів (Sitniks/ManyChat) + timeouts/retries

- **Чому саме так**: `httpx.AsyncClient` створюється у Sitniks на кожен виклик. Це зайвий overhead і немає централізованої політики таймаутів/ретраїв/логів.
- **Ризик**: неправильне reuse клієнта (не закрили), або глобальний клієнт без timeout → зависання.
- **Як перевірю**:
        - unit: клієнт створюється 1 раз на процес і закривається на shutdown
        - інтеграційно: під навантаженням немає вибуху TCP конектів

**Зміни (файли):**

- [`src/server/main.py`](src/server/main.py)
        - створити shared `httpx.AsyncClient` в lifespan (один для зовнішніх сервісів)
- [`src/integrations/crm/sitniks_chat_service.py`](src/integrations/crm/sitniks_chat_service.py)
        - інʼєктити клієнт або брати через фабрику/DI (без `async with AsyncClient` у кожному методі)
- [`src/integrations/manychat/api_client.py`](src/integrations/manychat/api_client.py)
        - переконатися, що клієнт закривається (вже є `close()`), підʼєднати до shutdown

---

### ЗАДАЧА 7: Maintenance без cron/infra (реалістично “працює зараз”)

- **Чому саме так**: ти сказав “у мене поки нічого немає” (без cron). Але таблиці `webhook_dedupe` і `mirt_memories` можуть рости.
- **Ризик**: якщо робити cleanup занадто часто → зайве навантаження на БД.
- **Як перевірю**:
        - метрика: кількість rows у `webhook_dedupe` і `mirt_memories` стабілізується
        - немає сплесків latency під час cleanup

**Рішення (decision tree):**

- Якщо ми реалізували **TTL‑фільтр на читанні** (ЗАДАЧА 3) → memory cleanup стає “опційним” (це тільки гігієна БД).
- Для `webhook_dedupe` (ідемпотентність) cleanup також опційний для логіки, але потрібний для розміру таблиці.

**Варіанти реалізації без cron (обрати один):**A) **Опортуністичний cleanup всередині існуючих Celery задач** (рекомендовано, якщо `CELERY_ENABLED=true`):

- раз на N запусків `summarization-check-1h` або `followups-check-15min` виконувати:
        - `WebhookDedupeStore.cleanup_expired_async()` (або SQL delete)
        - `MemoryService.cleanup_expired()` (якщо memory увімкнено)

B) **Опортуністичний cleanup у web‑процесі** (якщо Celery нема):

- у ManyChat webhook (push mode) раз на N запитів запускати `cleanup_expired_async()` в background (не блокуючи response)

C) **Вимкнути cleanup до появи cron**:

- приймаємо ріст таблиць, але система працює; паралельно плануємо cron пізніше.

**Файли:**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)
- [`src/workers/tasks/summarization.py`](src/workers/tasks/summarization.py) або [`src/workers/tasks/followups.py`](src/workers/tasks/followups.py)
- (опційно) [`docs/deployment/MEMORY_CLEANUP.md`](docs/deployment/MEMORY_CLEANUP.md) — уже є

---

## Додатковий “червоний прапорець” (внести в backlog)

### FOLLOWUPS night-mode + “кракозябри”

- У `src/workers/tasks/followups.py` є fallback рядок з `????????...` (кодування/хардкод).

- Якщо стратегія продукту: “пишемо клієнту в будь-який час” → night-mode треба прибрати або зробити нормальний текст через snippet/env.

- аналогічно у `search_facts()` (і будь‑яких інших “read” методах).

---

### ЗАДАЧА 4: Стандартизувати Postgres доступ у FastAPI на async pool (без блокування event loop)

- **Чому саме так**: у `src/server/routers/health.py` є `with psycopg.connect(...)` всередині `async def` → це блокує event loop і під навантаженням дає таймаути/деградацію. Ти вже обрав підхід **async‑pool‑everywhere**.
- **Ризик**: неправильний lifecycle пулу (не `open/close`), витоки конекшенів, або “pool not opened” у рантаймі.
- **Як перевірю**:
                - unit smoke: health endpoints не імпортують/не викликають sync connect
                - інтеграційно: `/health/*` під навантаженням тримає p95 без стрибків
                - метрика: кількість активних конекшенів/помилки pool

**Зміни (файли):**

- [`src/services/storage/postgres_pool.py`](src/services/storage/postgres_pool.py)
                - зробити пул керованим через lifespan: створення + `await pool.open()` + `await pool.close()`
                - явно фіксувати таймаути/параметри пулу
- [`src/server/main.py`](src/server/main.py)
                - у `lifespan` ініціалізувати Postgres pool на старті (і закривати на shutdown)
- [`src/server/routers/health.py`](src/server/routers/health.py)
                - замінити `psycopg.connect(...)` на `await get_postgres_pool(); async with pool.connection() ...`

**Decision tree (коли що робити):**

- Якщо `CELERY_ENABLED=true` і Redis доступний → health може також показувати стан worker’ів як зараз.
- Якщо `DATABASE_URL` відсутній → health повертає degraded/disabled без падіння.

---

### ЗАДАЧА 5: Прибрати `asyncio.run()` з web‑шляху (гарантія “не впаде в уже запущеному loop”)

- **Чому саме так**: `WebhookDedupeStore.check_and_mark()` зараз робить `asyncio.run(...)`. Це працює “поки пощастить”, але може впасти у проді, якщо буде викликано з async контексту (FastAPI).
- **Ризик**: зламати dedupe семантику → дублікати почнуть проходити або будуть false positives.
- **Як перевірю**:
                - тест, який викликає ManyChat webhook push mode з `message_id` і не отримує 500
                - тест, який гарантує: в async контексті викликається тільки async API (`await ...`)

**Зміни (файли):**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)
                - зробити **два** явних API:
                                - `async def check_and_mark_async(...) -> bool` (для FastAPI)
                                - `def check_and_mark(...) -> bool` (sync wrapper тільки для sync контекстів; без `asyncio.run` у web)
                - так само для cleanup: `cleanup_expired_async` + sync wrapper
- [`src/server/routers/webhooks_manychat.py`](src/server/routers/webhooks_manychat.py)
                - у push mode замінити виклик на `await dedupe_store.check_and_mark_async(...)`

---

### ЗАДАЧА 6: “Покласти по поличках” lifecycle HTTP клієнтів (Sitniks/ManyChat) + timeouts/retries

- **Чому саме так**: `httpx.AsyncClient` створюється у Sitniks на кожен виклик. Це зайвий overhead і немає централізованої політики таймаутів/ретраїв/логів.
- **Ризик**: неправильне reuse клієнта (не закрили), або глобальний клієнт без timeout → зависання.
- **Як перевірю**:
                - unit: клієнт створюється 1 раз на процес і закривається на shutdown
                - інтеграційно: під навантаженням немає вибуху TCP конектів

**Зміни (файли):**

- [`src/server/main.py`](src/server/main.py)
                - створити shared `httpx.AsyncClient` в lifespan (один для зовнішніх сервісів)
- [`src/integrations/crm/sitniks_chat_service.py`](src/integrations/crm/sitniks_chat_service.py)
                - інʼєктити клієнт або брати через фабрику/DI (без `async with AsyncClient` у кожному методі)
- [`src/integrations/manychat/api_client.py`](src/integrations/manychat/api_client.py)
                - переконатися, що клієнт закривається (вже є `close()`), підʼєднати до shutdown

---

### ЗАДАЧА 7: Maintenance без cron/infra (реалістично “працює зараз”)

- **Чому саме так**: ти сказав “у мене поки нічого немає” (без cron). Але таблиці `webhook_dedupe` і `mirt_memories` можуть рости.
- **Ризик**: якщо робити cleanup занадто часто → зайве навантаження на БД.
- **Як перевірю**:
                - метрика: кількість rows у `webhook_dedupe` і `mirt_memories` стабілізується
                - немає сплесків latency під час cleanup

**Рішення (decision tree):**

- Якщо ми реалізували **TTL‑фільтр на читанні** (ЗАДАЧА 3) → memory cleanup стає “опційним” (це тільки гігієна БД).
- Для `webhook_dedupe` (ідемпотентність) cleanup також опційний для логіки, але потрібний для розміру таблиці.

**Варіанти реалізації без cron (обрати один):**A) **Опортуністичний cleanup всередині існуючих Celery задач** (рекомендовано, якщо `CELERY_ENABLED=true`):

- раз на N запусків `summarization-check-1h` або `followups-check-15min` виконувати:
                - `WebhookDedupeStore.cleanup_expired_async()` (або SQL delete)
                - `MemoryService.cleanup_expired()` (якщо memory увімкнено)

B) **Опортуністичний cleanup у web‑процесі** (якщо Celery нема):

- у ManyChat webhook (push mode) раз на N запитів запускати `cleanup_expired_async()` в background (не блокуючи response)

C) **Вимкнути cleanup до появи cron**:

- приймаємо ріст таблиць, але система працює; паралельно плануємо cron пізніше.

**Файли:**

- [`src/services/webhook/webhook_dedupe.py`](src/services/webhook/webhook_dedupe.py)
- [`src/workers/tasks/summarization.py`](src/workers/tasks/summarization.py) або [`src/workers/tasks/followups.py`](src/workers/tasks/followups.py)
- (опційно) [`docs/deployment/MEMORY_CLEANUP.md`](docs/deployment/MEMORY_CLEANUP.md) — уже є

---

## Додатковий “червоний прапорець” (внести в backlog)

### FOLLOWUPS night-mode + “кракозябри”