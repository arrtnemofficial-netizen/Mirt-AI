# Mirt-AI

Референсний проєкт AI-стиліста для бренду MIRT, що використовує Grok 4.1 fast (через OpenRouter), Pydantic AI та LangGraph. Система реалізує state machine у system prompt, працює з окремим каталогом `data/catalog.json` і повертає строго типізований JSON-відповідь.

## Архітектура
- **System Prompt**: повний YAML із персоналією Ольги, guardrails, state machine `STATE0_INIT ... STATE9_OOD` та `OUTPUT_CONTRACT`. Каталог не вбудований у промт.
- **Каталог**: `data/catalog.json`, доступний через тулзу `catalog_tool` у Pydantic AI.
- **Pydantic AI + Grok 4.1 fast**: моделювання reasoning та сувора схема `AgentResponse`.
- **LangGraph**: зберігає історію, поточний стан, виконує модерацію користувацьких меседжів і викликає агента.

## Швидкий старт
1. Створіть `.venv` (Python 3.11+).
2. Встановіть залежності: `pip install -r requirements.txt`.
3. Додайте `.env` з ключами:
   ```env
   OPENROUTER_API_KEY=sk-...
   OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
   AI_MODEL=x-ai/grok-4.1-fast
   TELEGRAM_BOT_TOKEN=123456:bot-token-from-botfather
   PUBLIC_BASE_URL=https://your-domain.example
   TELEGRAM_WEBHOOK_PATH=/webhooks/telegram
   MANYCHAT_VERIFY_TOKEN=shared-manychat-token
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_API_KEY=service-or-anon-key
   SUPABASE_TABLE=agent_sessions
   ```
4. Запустіть демо-виклик (асинхронний):
   ```python
   from src.agents.graph import app

   state = {
       "messages": [{"role": "user", "content": "Привіт! Потрібна червона сукня 122 см."}],
       "metadata": {"session_id": "demo"},
       "current_state": "STATE1_DISCOVERY",
   }

   import asyncio
   print(asyncio.run(app.ainvoke(state)))
   ```

## Телеграм бот
- **Локально (polling)**: `python -m src.bot.telegram_bot` або виклик `run_polling()` у коді. Достатньо вставити свій `TELEGRAM_BOT_TOKEN` у `.env`.
- **Webhook**: підніміть FastAPI `uvicorn src.server.main:app --host 0.0.0.0 --port 8000`, задайте `PUBLIC_BASE_URL` (публічна адреса reverse-proxy/NGROK) — вебхук реєструється автоматично на старті.

## Збереження сесій у Supabase
- Додайте `SUPABASE_URL`, `SUPABASE_API_KEY` (service/anon key) та, за потреби, `SUPABASE_TABLE`.
- Таблиця має мати поля `session_id` (PK, text) і `state` (jsonb). Якщо у вас вже є таблиця — вкажіть її назву в `SUPABASE_TABLE`.
- При наявності змінних середовища сервер автоматично перемикається з in-memory на Supabase store без змін коду ботів.

## ManyChat / Instagram webhook
- Ендпоінт: `POST /webhooks/manychat` приймає ManyChat payload (`subscriber.id`, `message.text`).
- Авторизація: заголовок `X-Manychat-Token` має збігатися з `MANYCHAT_VERIFY_TOKEN` у `.env`.
- Відповідь: `{version:"v2", messages:[{type:"text",text:"..."},...], metadata:{current_state,...}}` — сумісно з ManyChat reply API.

## Файли
- `data/system_prompt_full.yaml` — повна інструкція для моделі.
- `data/catalog.json` — приклад каталогу.
- `src/core/models.py` — Pydantic-схеми відповіді.
- `src/services/catalog.py` — завантаження та пошук у каталозі для тулзи.
- `src/agents/pydantic_agent.py` — Pydantic AI агент з тулзою каталогу (ліниве створення клієнта).
- `src/agents/graph.py` — LangGraph-оркестратор з модерацією, підміною раннера для тестів.
- `src/services/moderation.py` — легка модерація (PII, заборонені терміни) з редагуванням вмісту.
- `src/services/metadata.py` — заповнення метаданих за замовчуванням для контракту.
- `src/conf/config.py` — конфігурація через `pydantic-settings`.
- `docs/STATUS.md` — зріз якості та прогалин щодо референсної архітектури.

## Тести
- Запуск усіх тестів: `pytest`.
- Тести не викликають зовнішній LLM — використовується заглушка агента і фейковий каталок.

## Безпека
- State machine та prompt вимагають фільтрації шкідливих запитів і відсутності вигаданих товарів.
- Особисті дані збираються мінімально (доставка без PII).

## Ліцензія
MIT
