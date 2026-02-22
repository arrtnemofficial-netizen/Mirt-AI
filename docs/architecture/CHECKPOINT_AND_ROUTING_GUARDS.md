# Mandatory PR Rules: Routing SSOT + Checkpoint Contract

Цей документ **обов'язковий для кожного PR**, який змінює router/intent/FSM/checkpointer.

## 1) SSOT для бізнес-умов переходів

- Бізнес-умови на рівні сирого тексту користувача (наприклад cancel/confirm/payment keyword) мають жити **тільки** в `intent-node`.
- `router_after_intent` працює лише з нормалізованими сигналами (`intent`, `state`, `has_image`) і не дублює keyword-умови.
- Guard покрито smoke-тестом `tests/smoke/test_router_intent_ssot_guard.py`.

## 2) Контракт checkpoint payload

Обов'язковий контракт payload:

- Є ключ `checkpoint_schema_version`.
- Версія строго дорівнює `1`.
- Дозволені ключі відповідають StateSchema + `checkpoint_schema_version`.
- Розмір payload не перевищує `CHECKPOINT_MAX_BYTES` (128 KiB).

Реалізація контракту:

- `src/agents/langgraph/checkpoint_contract.py`
- застосування версії у checkpointer через `ensure_checkpoint_schema_version(...)`.

## 3) Route vs FSM alignment

- Будь-яка зміна роутінгу або transition reducer має проходити regression gate:
  `tests/regression/test_route_vs_fsm_alignment.py`.
- Розходження route-рішення та FSM-рішення вважається blocker.

## 4) Vision exit policy

Після `vision` діє умовна матриця переходів:

- `validation`: якщо є `last_error` або заповнений `validation_errors`.
- `offer`: якщо є товари (`selected_products` або `offered_products`) **і** стан готовий до оферу:
  - `dialog_phase` у `{SIZE_COLOR_DONE, OFFER_MADE}`, або
  - `current_state == STATE_4_OFFER`.
- `end`: усі інші успішні сценарії після vision (віддати згенеровані vision-повідомлення користувачу і завершити хід).

Ця політика синхронізована між:
- `src/agents/langgraph/routers/post_process.py` (`route_after_vision`, `get_vision_routes`)
- `src/agents/langgraph/graph.py` (conditional edges для вузла `vision`).
