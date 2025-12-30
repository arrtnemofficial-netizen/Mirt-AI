---
name: Расширение manifest для payment-flow
overview: "Добавить 2-3 критичных action в manifest.json для payment-flow: PAYMENT_THANK_YOU (после payment proof), PAYMENT_SUBSCRIBE_REQUEST (после thank you), и опционально PAYMENT_REQUEST_RECEIPT (запрос чека). Это обеспечит строгий контроль и идемпотентность для системных сообщений, которые должны быть отправлены ровно один раз."
todos: []
---

# Расширение manifest для payment-flow

## Цель

Добавить в [`data/prompts/snippets/manifest.json`](data/prompts/snippets/manifest.json) системные actions для payment-flow, которые требуют:

- **Строгого контроля** (отправка ровно один раз)
- **Идемпотентности** (не дублировать)
- **Детерминированности** (не зависят от LLM перефразировки)

## Кандидаты для manifest

### 1. PAYMENT_THANK_YOU (критично)

**Когда**: После получения payment proof (payment_sub_phase = THANK_YOU)

**Snippet**: "Подяка за замовлення"

**Почему в manifest**: Должен быть отправлен **ровно один раз** после подтверждения оплаты. Сейчас хардкод в [`src/agents/langgraph/nodes/helpers/payment/delivery.py`](src/agents/langgraph/nodes/helpers/payment/delivery.py) (строка 152-157).

### 2. PAYMENT_SUBSCRIBE_REQUEST (критично)

**Когда**: Сразу после PAYMENT_THANK_YOU

**Snippet**: "Прохання підписатись (безпека)"

**Почему в manifest**: Должен быть отправлен **ровно один раз** после thank you. Сейчас хардкод в [`src/agents/langgraph/nodes/helpers/payment/delivery.py`](src/agents/langgraph/nodes/helpers/payment/delivery.py) (строка 160-168).

### 3. PAYMENT_REQUEST_RECEIPT (опционально)

**Когда**: После показа реквизитов, если payment proof еще не получен

**Snippet**: "Квитанція після оплати"

**Почему в manifest**: Можно отправлять несколько раз (если пользователь не прислал), но лучше контролировать через manifest для логирования/метрик.

## Изменения

### 1. Обновить manifest.json

Добавить actions:

```json
{
  "actions": {
    "PAYMENT_REQUEST_DATA": { ... },  // уже есть
    "PAYMENT_THANK_YOU": {
      "snippet_header": "Подяка за замовлення",
      "idempotency_key": "payment_thank_you_sent",
      "description": "Благодарность после подтверждения оплаты (отправляется ровно один раз)"
    },
    "PAYMENT_SUBSCRIBE_REQUEST": {
      "snippet_header": "Прохання підписатись (безпека)",
      "idempotency_key": "payment_subscribe_sent",
      "description": "Просьба подписаться на резервный канал (отправляется ровно один раз после thank you)"
    },
    "PAYMENT_REQUEST_RECEIPT": {
      "snippet_header": "Квитанція після оплати",
      "idempotency_key": "payment_receipt_request_sent",
      "description": "Запрос чека после показа реквизитов (можно отправлять повторно, но контролируем через manifest)"
    }
  },
  "rules": [
    { ... },  // PAYMENT_REQUEST_DATA уже есть
    {
      "condition": {
        "state": "STATE_5_PAYMENT_DELIVERY",
        "payment_sub_phase": "THANK_YOU"
      },
      "action": "PAYMENT_THANK_YOU"
    },
    {
      "condition": {
        "state": "STATE_5_PAYMENT_DELIVERY",
        "payment_sub_phase": "THANK_YOU",
        "after_action": "PAYMENT_THANK_YOU"  // после отправки thank you
      },
      "action": "PAYMENT_SUBSCRIBE_REQUEST"
    },
    {
      "condition": {
        "state": "STATE_5_PAYMENT_DELIVERY",
        "payment_sub_phase": "SHOW_PAYMENT",
        "payment_receipt_requested": false
      },
      "action": "PAYMENT_REQUEST_RECEIPT"
    }
  ]
}
```

**Вопрос**: Нужна ли поддержка `after_action` в policy.py, или лучше сделать два отдельных вызова в `delivery.py`?

### 2. Обновить delivery.py

В `_handle_payment_proof_received()` заменить хардкод на использование manifest:

```python
# Вместо:
thank_you_snippets = get_snippet_by_header("Подяка за замовлення")
subscribe_snippets = get_snippet_by_header("Прохання підписатись (безпека)")

# Использовать:
from src.agents.langgraph.fsm.policy import determine_response_policy

# Для thank you
policy1 = determine_response_policy(
    next_state=State.STATE_5_PAYMENT_DELIVERY.value,
    payment_sub_phase="THANK_YOU",
    metadata=metadata,
    session_id=session_id,
)
if policy1.snippet_name:
    # загрузить и отправить snippet
    # установить флаг policy1.snippet_sent_flag = True

# Для subscribe (после thank you)
policy2 = determine_response_policy(
    next_state=State.STATE_5_PAYMENT_DELIVERY.value,
    payment_sub_phase="THANK_YOU",
    metadata=metadata,  # уже с флагом thank_you_sent
    session_id=session_id,
)
```

**Проблема**: Текущий `determine_response_policy()` не поддерживает "последовательность" (after_action). Нужно либо:

- **Вариант A**: Добавить поддержку `after_action` в policy.py
- **Вариант B**: Сделать два отдельных правила в manifest (subscribe только если `payment_thank_you_sent == true`)
- **Вариант C**: Оставить subscribe в delivery.py, но использовать manifest для thank you

### 3. Обновить policy.py (если выбран вариант B)

Добавить поддержку проверки флагов в conditions:

```python
# В determine_response_policy() добавить проверку:
if condition.get("payment_thank_you_sent"):
    if not metadata.get("payment_thank_you_sent", False):
        continue  # правило не подходит
```



## Рекомендация

**Начать с минимального**: добавить только `PAYMENT_THANK_YOU` в manifest, а `PAYMENT_SUBSCRIBE_REQUEST` оставить в delivery.py (но использовать manifest для thank you). Это проще и не требует изменений в policy.py.Если нужна полная централизация - выбрать вариант B (проверка флагов в conditions).

## Тесты

Добавить в [`tests/test_fsm_contract.py`](tests/test_fsm_contract.py):

- `test_payment_thank_you_sent_once`: thank you отправляется ровно один раз