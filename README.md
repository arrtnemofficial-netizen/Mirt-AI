# Mirt-AI

Референсний проєкт AI-стиліста для бренду MIRT, що використовує Grok 4.1 fast (через OpenRouter), Pydantic AI та LangGraph. Система реалізує state machine у system prompt (v6.0-final), працює ВИКЛЮЧНО через Supabase tools і повертає строго типізований JSON-відповідь.

## Архітектура
- **System Prompt**: повний YAML v6.0-final із персоналією Ольги, guardrails, state machine `STATE_0_INIT ... STATE_9_OOD` та `OUTPUT_CONTRACT`. Каталог не вбудований у промт.
- **Каталог**: `data/catalog.json` як еталон для імпорту в Supabase, а також `data/catalog.csv` з ембеддингами для таблиці `mirt_product_embeddings`.
- **Supabase tools**: `T_SUPABASE_SEARCH_BY_QUERY`, `T_SUPABASE_GET_BY_ID`, `T_SUPABASE_GET_BY_PHOTO_URL` — єдине джерело правди для товарів. Локальний JSON використовується лише для імпорту або офлайн-генерації CSV.
- **Pydantic AI + Grok 4.1 fast**: моделювання reasoning та сувора схема `AgentResponse` з metadata.session_id, intent, current_state.
- **LangGraph**: зберігає історію, поточний стан, виконує модерацію користувацьких меседжів і викликає агента.

### Антивіб-код підхід
- Supabase-інструменти обгорнуті ретраями та повертають лише валідувані записи (id, ціна, фото, розміри); у разі збою підіймають керовану помилку `SupabaseToolError`.
- Ембеддинги завжди детерміновані: якщо ключ OpenAI відсутній, застосовується хеш-фолбек із фіксованою розмірністю.
- metadata.session_id не заповнюється вигаданими значеннями: якщо його не передали, лишається порожнім, що відповідає контракту v6.0-final.

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
   SUPABASE_MESSAGES_TABLE=messages
   SUPABASE_USERS_TABLE=users
   SUPABASE_CATALOG_TABLE=mirt_products
   SUPABASE_EMBEDDINGS_TABLE=mirt_product_embeddings
   SUPABASE_MATCH_RPC=match_mirt_products
   OPENAI_API_KEY=sk-openai-...  # для ембеддингів (опційно, інакше детермінований хеш)
   SUMMARY_RETENTION_DAYS=3
   FOLLOWUP_DELAYS_HOURS=24,72
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

## Збереження сесій, повідомлень і каталогу у Supabase
- Сесії: таблиця `SUPABASE_TABLE` із полями `session_id` (PK, text) і `state` (jsonb). Автоматичне перемикання на Supabase при наявності env.
- Повідомлення: таблиця `SUPABASE_MESSAGES_TABLE` з полями `session_id`, `role`, `content`, `created_at` (timestamptz), `tags` (array/text[]). Усі вхідні та вихідні повідомлення записуються туди; тег `humanNeeded-wd` ставиться на відповіді з ескалацією.
- Каталог (RAG): таблиця `mirt_products` з полями з system prompt (category/subcategory/sizes/material/price_uniform/price_by_size/colors). Ембеддинги — таблиця `mirt_product_embeddings` (vector(1536)), RPC `match_mirt_products` повертає top-N. `data/catalog.json` та `data/catalog.csv` слугують єдиним джерелом для імпорту.

## ManyChat / Instagram webhook
- Ендпоінт: `POST /webhooks/manychat` приймає ManyChat payload (`subscriber.id`, `message.text`).
- Авторизація: заголовок `X-Manychat-Token` має збігатися з `MANYCHAT_VERIFY_TOKEN` у `.env`.
- Відповідь: `{version:"v2", messages:[{type:"text",text:"..."},...], metadata:{current_state,...}}` — сумісно з ManyChat reply API.

### Автоматизація переупаковки
- Ендпоінт: `POST /automation/mirt-summarize-prod-v1` з тілом `{ "session_id": "..." }`.
- Логіка: якщо від останнього повідомлення минуло `SUMMARY_RETENTION_DAYS` днів (за замовчуванням 3), усі повідомлення по `session_id` перетворюються у саммарі, записуються у поле `summary` таблиці `SUPABASE_USERS_TABLE`, старі повідомлення видаляються з `SUPABASE_MESSAGES_TABLE`.
- При переупаковці тег `humanNeeded-wd` автоматично знімається, щоб закрити SLA ескалації.

### Автоматизація фолоуапів
- Ендпоінт: `POST /automation/mirt-followups-prod-v1` з тілом `{ "session_id": "...", "schedule_hours": [24, 72] }`.
- Якщо `schedule_hours` не заданий, використовується `FOLLOWUP_DELAYS_HOURS` з `.env` (кома-сепарований список годин). Система перевіряє дату останньої активності та кількість уже відправлених фолоуапів (теги `followup-sent-*` у таблиці повідомлень) і, якщо настав час, записує нове повідомлення з нагадуванням у `SUPABASE_MESSAGES_TABLE`.
- Відправку повідомлень на канали (Telegram, ManyChat) можна реалізувати власним шедулером: достатньо викликати цей ендпоінт і надіслати сформований текст на потрібний канал.

## Файли
- `data/system_prompt_full.yaml` — повна інструкція для моделі.
- `data/catalog.json` — приклад каталогу.
- `data/catalog.csv` — каталожний CSV із вектором ембеддингу для кожної позиції (згенерований скриптом `scripts/catalog_to_csv.py`).
- `src/core/models.py` — Pydantic-схеми відповіді.
- `src/services/catalog.py` — локальний JSON-каталог (для імпорту/офлайн сценаріїв).
- `src/services/supabase_tools.py` — єдиний набір тулзів `T_SUPABASE_*` для моделі.
- `src/agents/pydantic_agent.py` — Pydantic AI агент з Supabase-тулзами (лише при наявності клієнта Supabase).
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
