# ПЛАН ПОКРАЩЕННЯ ДО PRODUCTION-READY

> Мета: Зробити систему, до якої **ні в кого не буде питань**.
> Фокус: Надійність, швидкість, масштабованість (без ембеддінгів фото).
>
> **Статус на 2025-12-07:** Частину цього плану вже виконано — 
> Vision тепер використовує `data/vision/products_master.yaml` + генератор артефактів
> (`data/vision/generate.py`, `scripts/generate_vision_artifacts.py`) замість ручного редагування JSON.
> Решта пунктів нижче залишаються roadmap'ом для подальшого розвитку (Supabase як основне джерело, кешування, CI/CD тощо).

---

## ФАЗА 1: БАЗА ДАНИХ ЗАМІСТЬ JSON (Критично!)

### Проблема зараз
- Ціни/SKU/залишки захардкоджені в `vision_guide.json`
- Зміна ціни = редагування коду + деплой
- Ризик продати товар, якого немає

### Рішення

```
┌─────────────────────────────────────────────────────────────┐
│                    CATALOG SERVICE                          │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL / SQLite                                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ products                                             │   │
│  │ - id (PK)                                            │   │
│  │ - sku (unique)                                       │   │
│  │ - name                                               │   │
│  │ - price                                              │   │
│  │ - category                                           │   │
│  │ - sizes (JSON)                                       │   │
│  │ - colors (JSON)                                      │   │
│  │ - in_stock (boolean)                                 │   │
│  │ - visual_features (TEXT) ← для Vision               │   │
│  │ - recognition_tips (TEXT)                            │   │
│  │ - updated_at                                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Файли для створення

```
src/
├── db/
│   ├── __init__.py
│   ├── models.py          # SQLAlchemy моделі
│   ├── connection.py      # Async connection pool
│   └── migrations/        # Alembic міграції
├── services/
│   └── catalog_service.py # get_product(), search(), check_stock()
```

### Що зміниться
- `search_products()` tool → бере з БД, не з JSON
- Ціни завжди актуальні
- Можна додати адмін-панель для менеджера

### Складність: 🟡 Середня (2-3 дні)

---

## ФАЗА 2: КЕШУВАННЯ ТА ШВИДКІСТЬ

### Проблема зараз
- Кожен запит до LLM = 5-15 секунд
- Повторні запити про той самий товар = ті ж 5-15 секунд
- Користувач пише "ало?" поки бот думає

### Рішення

```
┌─────────────────────────────────────────────────────────────┐
│                    CACHE LAYER (Redis)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. PRODUCT CACHE (TTL: 1 година)                          │
│     key: "product:{sku}"                                    │
│     value: {name, price, sizes, colors, stock}             │
│                                                             │
│  2. VISION RESULT CACHE (TTL: 24 години)                   │
│     key: "vision:{image_hash}"                              │
│     value: {identified_product, confidence}                │
│                                                             │
│  3. SESSION CACHE (TTL: 30 хвилин)                         │
│     key: "session:{user_id}"                                │
│     value: {current_state, selected_products, context}     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Image Hashing (без ембеддінгів!)
```python
import hashlib
from PIL import Image
import imagehash

def get_image_hash(image_bytes: bytes) -> str:
    """Перцептивний хеш — схожі картинки = схожий хеш."""
    img = Image.open(io.BytesIO(image_bytes))
    return str(imagehash.phash(img))  # 64-bit hash

# Використання:
hash = get_image_hash(photo_bytes)
cached = redis.get(f"vision:{hash}")
if cached:
    return cached  # Миттєво! Без LLM.
```

### Файли для створення

```
src/
├── cache/
│   ├── __init__.py
│   ├── redis_client.py    # Async Redis connection
│   ├── product_cache.py   # get/set product
│   ├── vision_cache.py    # get/set vision results
│   └── session_cache.py   # User session state
```

### Що дасть
- **Повторні фото** → відповідь за 50ms замість 10s
- **Товари** → кеш, не DB query кожен раз
- **Сесії** → швидке відновлення контексту

### Складність: 🟡 Середня (2 дні)

---

## ФАЗА 3: RAG ДЛЯ ПРОМПТІВ (Текстовий)

### Проблема зараз
- Vision промпт = 11,500+ символів (ВСІ товари)
- Більше товарів = промпт не влізе в контекст
- Модель "забуває" кінець промпту

### Рішення: Текстовий RAG (без ембеддінгів картинок)

```
┌─────────────────────────────────────────────────────────────┐
│                    TEXT RAG SYSTEM                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. ІНДЕКСАЦІЯ (один раз при старті):                      │
│     - Кожен товар → текстовий опис                         │
│     - Опис → text embedding (OpenAI ada-002 / local)       │
│     - Зберігаємо в ChromaDB / Qdrant                        │
│                                                             │
│  2. RUNTIME (при кожному фото):                            │
│     - Витягуємо з фото: "рожевий костюм плюш"              │
│     - Шукаємо TOP-3 схожих товари по тексту                │
│     - В промпт йдуть ТІЛЬКИ ці 3 товари (~1500 символів)   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Як це працює

```python
# При старті (індексація)
for product in all_products:
    text = f"{product.name} {product.visual_features} {product.recognition_tips}"
    embedding = openai.embed(text)
    chroma.add(id=product.sku, embedding=embedding, metadata=product)

# При запиті (runtime)
user_query = "рожевий костюм з блискавкою"
similar = chroma.query(user_query, top_k=3)
# Повертає: [Мрія, Лагуна, Ритм]

# В промпт йдуть ТІЛЬКИ ці 3 товари
vision_prompt = base_algorithm + format_products(similar)
# Замість 11k символів → 2k символів!
```

### Що дасть
- **Масштабування**: 1000 товарів працюють так само швидко як 10
- **Дешевше**: Менше токенів = менше грошей
- **Точніше**: Модель фокусується на релевантних товарах

### Складність: 🟠 Складна (3-4 дні)

---

## ФАЗА 4: МОНІТОРИНГ ТА АЛЕРТИ

### Проблема зараз
- Не знаєш, скільки запитів падає
- Не знаєш, де bottleneck
- Дізнаєшся про проблему від клієнта

### Рішення

```
┌─────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY STACK                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  METRICS (Prometheus / Logfire):                           │
│  - vision_requests_total                                    │
│  - vision_confidence_avg                                    │
│  - vision_latency_seconds                                   │
│  - llm_tokens_used                                          │
│  - escalation_rate                                          │
│  - cache_hit_rate                                           │
│                                                             │
│  ALERTS:                                                    │
│  - vision_confidence < 0.5 для >20% запитів → Telegram     │
│  - latency > 15s → Telegram                                 │
│  - error_rate > 5% → Telegram                               │
│  - daily_cost > $X → Telegram                               │
│                                                             │
│  DASHBOARDS:                                                │
│  - Grafana: Latency, Errors, Cost                          │
│  - Custom: Conversion funnel (init → discovery → purchase) │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Файли для створення

```
src/
├── observability/
│   ├── __init__.py
│   ├── metrics.py         # Prometheus counters/histograms
│   ├── alerts.py          # Alert rules + Telegram notify
│   └── cost_tracker.py    # Track LLM token usage
```

### Що дасть
- **Проактивність**: Ти знаєш про проблему ДО клієнта
- **Оптимізація**: Бачиш, де система гальмує
- **Бюджет**: Контролюєш витрати на LLM

### Складність: 🟢 Легка (1-2 дні)

---

## ФАЗА 5: ТЕСТИ ТА CI/CD

### Проблема зараз
- Є базові тести, але не на всі ноди
- Немає integration tests
- Деплой вручну (ризик помилки)

### Рішення

```
┌─────────────────────────────────────────────────────────────┐
│                    TESTING PYRAMID                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  UNIT TESTS (є, розширити):                                │
│  - test_vision_node.py                                      │
│  - test_agent_node.py                                       │
│  - test_edges_routing.py                                    │
│  - test_catalog_service.py                                  │
│                                                             │
│  INTEGRATION TESTS (додати):                               │
│  - test_full_conversation_flow.py                          │
│  - test_vision_to_purchase.py                               │
│  - test_escalation_flow.py                                  │
│                                                             │
│  E2E TESTS (додати):                                       │
│  - test_telegram_bot_e2e.py (mock Telegram API)            │
│                                                             │
│  EVAL TESTS (для LLM):                                     │
│  - 50+ реальних фото → очікуваний SKU                      │
│  - Автоматичний прогін при кожному деплої                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest tests/ --cov=src --cov-fail-under=80
      
      - name: Run LLM evals
        run: python scripts/run_vision_evals.py
        
      - name: Check prompts
        run: python scripts/validate_prompts.py

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: ./scripts/deploy.sh
```

### Що дасть
- **Впевненість**: Деплоїш без страху
- **Регресії**: Ловиш баги до продакшену
- **Автоматизація**: Нема ручної роботи

### Складність: 🟡 Середня (2-3 дні)

---

## ФАЗА 6: GRACEFUL DEGRADATION (Бонус)

### Що робити, коли LLM лежить?

```python
# src/agents/fallback.py

async def vision_with_fallback(image_url: str, deps: AgentDeps):
    try:
        # Спробуй основну модель
        return await run_vision(image_url, deps, model="grok-4")
    except (TimeoutError, APIError):
        try:
            # Fallback на дешевшу модель
            return await run_vision(image_url, deps, model="gpt-4o-mini")
        except:
            # Останній fallback — людина
            return VisionResponse(
                reply_to_user="Вибачте, зараз не можу проаналізувати фото. "
                              "Опишіть, будь ласка, що шукаєте?",
                needs_clarification=True,
                escalation="L1"  # Ескалація на менеджера
            )
```

---

## ПІДСУМОК: ROADMAP

| Фаза | Що | Пріоритет | Час | Результат |
|------|-----|-----------|-----|-----------|
| 1 | БД замість JSON | 🔴 КРИТИЧНО | 2-3 дні | Актуальні ціни/залишки |
| 2 | Кешування | 🔴 КРИТИЧНО | 2 дні | Швидкість 10x |
| 3 | Text RAG | 🟡 ВАЖЛИВО | 3-4 дні | Масштабування |
| 4 | Моніторинг | 🟡 ВАЖЛИВО | 1-2 дні | Проактивність |
| 5 | Тести + CI/CD | 🟢 БАЖАНО | 2-3 дні | Впевненість |
| 6 | Fallback | 🟢 БАЖАНО | 1 день | Надійність |

**Загалом: 11-15 днів** для повного production-ready рівня.

---

## ПІСЛЯ ЦЬОГО ПЛАНУ

Твоя система буде:
- ✅ **Швидкою** — відповідь за 1-2 сек (кеш) замість 10+ сек
- ✅ **Надійною** — fallback, алерти, тести
- ✅ **Масштабованою** — 1000 товарів = ок
- ✅ **Підтримуваною** — ціни в БД, не в коді
- ✅ **Прозорою** — метрики, дашборди, логи

**Ні в кого не буде питань. Це буде Enterprise-grade.**
