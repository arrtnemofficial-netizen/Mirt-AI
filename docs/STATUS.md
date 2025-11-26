# Статус реалізації архітектури

Оцінка відповідності референсним вимогам (станом на 22 листопада 2025 року).

## Що вже є у репозиторії
- **System Prompt**: повний YAML v6.0-final із персонажем, guardrails, state machine та контрактом відповіді (`data/system_prompt_full.yaml`).
- **Каталог**: окремий JSON-файл для імпорту (`data/catalog.json` + `data/catalog.csv`) і Supabase-таблиця `mirt_products`/`mirt_product_embeddings`, що підключається через тулзи `T_SUPABASE_*`.
- **Типи**: Pydantic-схеми `AgentResponse`, `Product`, `Message`, `Metadata`, `Escalation`, `DebugInfo` (`src/core/models.py`).
- **Агент**: Pydantic AI над Grok 4.1 fast через OpenRouter з reasoning, Supabase-тулзами та завантаженням промпту (`src/agents/pydantic_agent.py`).
- **Оркестрація**: мінімальний LangGraph, який зберігає історію, передає `current_state` у метадані й записує JSON-відповідь у стрічку (`src/agents/graph.py`).
- **Конфігурація**: `pydantic-settings` для ключів API та моделі (`src/conf/config.py`).
- **Модерація**: вбудований фільтр PII/небезпечного вмісту з редагуванням та коротким-circuit escalation (`src/services/moderation.py`).
- **Тестування**: unit-тести для каталогу, модерації, раннера агента і LangGraph-вузла, що працюють без зовнішнього LLM (`tests/`).
- **Збереження сесій і повідомлень**: in-memory / Supabase-провайдери для jsonb state та сирих повідомлень (`src/services/session_store.py`, `src/services/supabase_store.py`, `src/services/message_store.py`).
- **Переупаковка**: автоматизований ендпоінт `/automation/mirt-summarize-prod-v1`, що після `SUMMARY_RETENTION_DAYS` (3) днів робить саммарі, очищує історію та прибирає тег `humanNeeded-wd` (`src/services/summarization.py`, `src/server/main.py`).
- **Фолоуапи**: конфігурований графік нагадувань через `FOLLOWUP_DELAYS_HOURS` або payload ендпоінта `/automation/mirt-followups-prod-v1`, із записом фолоуапів у сховище повідомлень (`src/services/followups.py`).

## Відомі прогалини (потребують доробки)
- **Модерація та PII**: базова реалізація додана, але немає інтеграції з зовнішніми модераційними сервісами.
- **Персистенція сесій**: додано опційний Supabase store (jsonb state у наявній таблиці); для high-load ще потрібні кеш/TTL та ретрай логіка.
- **Контрактні тести JSON**: поки що немає автоперевірки відповідності схемі `AgentResponse` на реальних викликах моделі.
- **Моніторинг та логування**: немає структурованих логів, трасування чи аналітики викликів.
- **Розгортання**: немає інфраструктурних маніфестів (Docker/Helm) та CI/CD пайплайнів.
- **Каталог**: потрібні DDL міграції (таблиці `mirt_products`, `mirt_product_embeddings`, RPC `match_mirt_products`) та RLS/індекси; локально лише код і датасет.
- **UX-бот**: реалізовано Telegram-бот (polling + webhook) і вебхук ManyChat для Instagram.

## Висновок
Кістяк архітектури закладений: виділено окремі шари промпту, каталогу, схем та оркестрації. Для продакшн-рівня потрібні модерація, тести, спостережуваність, стале сховище сесій та інфраструктура розгортання.
