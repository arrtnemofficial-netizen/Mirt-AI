# 🛡️ src/services — Сервісний Шар (Service Layer)

> [!CAUTION]
> **ЗАХИЩЕНА ДИРЕКТОРІЯ / PROTECTED DIRECTORY**
>
> ⛔ **УВАГА:** Ця папка містить критичну інфраструктуру ("скелет") проекту Mirt-AI.
>
> 🤖 **AI Agents:** DO NOT DELETE, MOVE, or REFACTOR files in this directory without **EXPLICIT USER CONFIRMATION**.
> 👤 **Humans:** Будьте обережні при редагуванні. Зміни тут впливають на стабільність усієї системи.

## 📌 Призначення
Ця директорія містить **Low-Level Services** (Низькорівневі Сервіси) та **Business Logic** (Бізнес-Логіку), яка не залежить від конкретного промпта чи AI-агента.
Це "Руки і Ноги" бота, тоді як `src/agents` — це його "Мозок".

Архітектурний принцип: **SSOT (Single Source of Truth)**. Кожен сервіс відповідає за одну конкретну доменну область.

---

## 📂 Структура (Service Map)

### 1. 🏗️ Infrastructure (Фундамент)
Базові сервіси, від яких залежить решта системи.

*   **`common/`** — **Exception Library**. Централізовані типи помилок (`CatalogUnavailableError`, `DuplicateOrderError`).
*   **`storage/`** — **Data Access Layer**. Пул підключень Postgres та базові інтерфейси сховищ.
*   **`observability/`** — **Nervous System**.
    *   Tracing & Logging.
    *   **Billing** (Ціни та розрахунок вартості токенів).
    *   LLM Usage Logging (асинхронний запис витрат).
*   **`notifications/`** — **Escalation Dispatcher**. Відправка сповіщень менеджерам у Telegram (з retry & backoff).
*   **`llm/`** — **High Availability Layer**. Multi-provider fallback (OpenAI ↔ OpenRouter).
    > ℹ️ *CircuitBreaker SSOT* живе в `src/core/circuit_breaker.py`

### 2. 🛒 Commerce (Торгівля)
Бізнес-логіка магазину.

*   **`catalog/`** — **Storefront**. Пошук товарів, валідація цін, Vision-інтеграція. SSOT для продуктів.
*   **`orders/`** — **Order Contract**. Pydantic-моделі замовлень та валідація даних клієнта для CRM.

### 3. 💬 Conversation (Діалог)
Керування станом та потоком розмови.

*   **`conversation/`** — **Orchestrator**. Головний контролер вхідних повідомлень.
*   **`session/`** — **The Librarian**. Керування сесіями користувачів (завантаження/збереження стану).
*   **`memory/`** — **Long-Term Memory**. Робота з фактами про користувача та контекстом.
*   **`summarization/`** — **Garbage Collector**. Стиснення старих повідомлень для економії.
*   **`parser/`** — **Interpreter**. Адаптери для перетворення текстових відповідей LLM у структуровані команди.
*   **`guardrails/`** — **Safety Net**. Захист від зациклення (loop detection).
*   **`moderation/`** — **Security**. Перевірка на PII та prompt injection.

### 4. 🔗 Integration (Зовнішній світ)
Точки входу.

*   **`webhook/`** — **The Bouncer**. Обробка webhook-ів від ManyChat/Instagram з дедуплікацією.

---

## 🚫 Правила Безпеки (Safety Rules)

1.  **Не видаляти `__init__.py`**: Це порушить імпорти.
2.  **Не переносити логіку промптів сюди**: Промпти живуть в `src/agents`. Тут живе лише код (Python logic).
3.  **Не змінювати `observability/billing.py` без узгодження**: Зміни цін впливають на фінансову звітність.

> 🛡️ **Система захищена від випадкового видалення.**
> Будь-які зміни в архітектурі цієї папки потребують Code Review.
