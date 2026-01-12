# 🧩 Parser Service — Перекладач

> **Роль:** "Translator" (Перекладач)
> **Відповідальність:** Конвертація сириx даних (LLM JSON, Pydantic Models) у єдиний формат `AgentResponse`.

Цей модуль гарантує, що решта системи (Frontend, API) працює з чистими, типізованими об'єктами, а не з "сирим" текстом.

---

## 🛠️ Функціонал

### 1. `parse_llm_output`
Обробляє відповіді від LangGraph нод.
*   **Вхід:** JSON рядок (`'{"event": "reply", "messages": [...]}'`)
*   **Вихід:** Об'єкт `AgentResponse`.
*   **Fallback:** Якщо вхід це не JSON ("Привіт, я тут"), він автоматично загортає це в текстове повідомлення. *System never crashes on bad JSON.*

### 2. `convert_support_response`
Адаптер для PydanticAI агентів (`support`, `vision`).
*   Ці агенти повертають свої специфічні Pydantic моделі (`SupportResponse`).
*   Ця функція перетворює їх на універсальний `AgentResponse` (Core Model).
*   **Feature:** Автоматично фіксить "биті" дані (наприклад, `price=0` або `id=None` для товарів), щоб не ламати фронтенд.

---

## 🔗 Використання (Usage)

Використовується ексклюзивно в **`src/services/conversation/conversation.py`**.

```python
# Приклад
try:
    response = parse_llm_output(llm_result_json)
except Exception:
    # Parser має вбудований fallback, помилок не буде
    pass
```

## 🏗️ Чому це окремий сервіс?
Щоб забрати "брудну" логіку парсингу JSON та мапінгу полів з головного `ConversationHandler`.
Це робить код оркестратора чистим і читабельним.
