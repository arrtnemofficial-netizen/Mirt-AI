# Статус реалізації архітектури

Оцінка відповідності референсним вимогам (станом на 22 листопада 2025 року).

## Що вже є у репозиторії
- **System Prompt**: повний YAML із персонажем, guardrails, state machine та контрактом відповіді (`data/system_prompt_full.yaml`).
- **Каталог**: окремий JSON-файл або Supabase-таблиця, що підключається через тулзу `catalog_tool` (`data/catalog.json` або `SUPABASE_CATALOG_TABLE`).
- **Типи**: Pydantic-схеми `AgentResponse`, `Product`, `Message`, `Metadata`, `Escalation`, `DebugInfo` (`src/core/models.py`).
- **Агент**: Pydantic AI над Grok 4.1 fast через OpenRouter з reasoning, інструментом каталогу та завантаженням промпту (`src/agents/pydantic_agent.py`).
- **Оркестрація**: мінімальний LangGraph, який зберігає історію, передає `current_state` у метадані й записує JSON-відповідь у стрічку (`src/agents/graph.py`).
- **Конфігурація**: `pydantic-settings` для ключів API та моделі (`src/conf/config.py`).
- **Модерація**: вбудований фільтр PII/небезпечного вмісту з редагуванням та коротким-circuit escalation (`src/services/moderation.py`).
- **Тестування**: unit-тести для каталогу, модерації, раннера агента і LangGraph-вузла, що працюють без зовнішнього LLM (`tests/`).
- **Збереження сесій і повідомлень**: in-memory / Supabase-провайдери для jsonb state та сирих повідомлень (`src/services/session_store.py`, `src/services/supabase_store.py`, `src/services/message_store.py`).
- **Переупаковка**: автоматизований ендпоінт `/automation/mirt-summarize-prod-v1`, що після `SUMMARY_RETENTION_DAYS` (3) днів робить саммарі, очищує історію та прибирає тег `humanNeeded-wd` (`src/services/summarization.py`, `src/server/main.py`).

## Відомі прогалини (потребують доробки)
- **Модерація та PII**: базова реалізація додана, але немає інтеграції з зовнішніми модераційними сервісами.
- **Персистенція сесій**: додано опційний Supabase store (jsonb state у наявній таблиці); для high-load ще потрібні кеш/TTL та ретрай логіка.
- **Контрактні тести JSON**: поки що немає автоперевірки відповідності схемі `AgentResponse` на реальних викликах моделі.
- **Моніторинг та логування**: немає структурованих логів, трасування чи аналітики викликів.
- **Розгортання**: немає інфраструктурних маніфестів (Docker/Helm) та CI/CD пайплайнів.
- **Каталог**: базовий Supabase RAG (ilike по name/category); розширений пошук (вектори, фільтри) ще потрібно додати.
- **UX-бот**: реалізовано Telegram-бот (polling + webhook) і вебхук ManyChat для Instagram.

## Висновок
Кістяк архітектури закладений: виділено окремі шари промпту, каталогу, схем та оркестрації. Для продакшн-рівня потрібні модерація, тести, спостережуваність, стале сховище сесій та інфраструктура розгортання.
