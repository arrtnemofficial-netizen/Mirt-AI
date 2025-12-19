# Архітектура агентів (LangGraph)

## Що таке LangGraph у MIRT

Наш граф складається з набору вузлів, кожен з яких виконує окрему логіку:
- **Moderation / Intent / Vision / Offer / Payment / Upsell / Escalation**.
- Підтримка **HITL** (interrupt перед payment).
- Повна **persistence** через Postgres checkpointer.

Див. `src/agents/langgraph/graph.py` для повної конфігурації.

## Стан (`ConversationState`)

Визначено в `src/agents/langgraph/state.py`. Ключові поля:

| Поле          | Опис                                                                 |
|---------------|----------------------------------------------------------------------|
| `messages`    | Поточна історія діалогу. Тримайте в межах `STATE_MAX_MESSAGES`.       |
| `dialog_phase`| Поточна фаза FSM (див. `docs/FSM_TRANSITION_TABLE.md`).               |
| `metadata`    | Будь-які сервісні дані (channel, trace_id, vision_confidence тощо).   |
| `selected_products`, `agent_response`, `escalation_level` | Вихідні дані для ManyChat/Telegram. |

Trim-політики:
- `STATE_MAX_MESSAGES`
- `LLM_MAX_HISTORY_MESSAGES`
- `CHECKPOINTER_MAX_MESSAGES`

Конфіг описано в `src/services/trim_policy.py`.

## Checkpointer

Модуль `src/agents/langgraph/checkpointer.py`:
- Будує пул `AsyncConnectionPool` (Supabase/Postgres).
- Логує повільні операції (`aget_tuple`, `aput`).
- Робить компакцію payload (`CHECKPOINTER_MAX_MESSAGE_CHARS`, `CHECKPOINTER_DROP_BASE64`).

Для моніторингу див. `docs/OBSERVABILITY_RUNBOOK.md`.

## Як розширювати граф
1. Додайте вузол у `graph.py`.
2. Оновіть FSM таблицю.
3. Додайте промпт у `src/core/prompt_registry.py`.
4. Налаштуйте observability (нові метрики / події).

