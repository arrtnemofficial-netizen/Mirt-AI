# FSM Transition Table - MIRT AI Bot

> **FREEZE NOTICE**: Цей документ є frozen specification. Будь-які зміни в роутингу
> повинні СПОЧАТКУ бути задокументовані тут, а ПОТІМ імплементовані в коді.

## Стани (States)

| State | Опис | Escalation? |
|-------|------|-------------|
| `STATE_0_INIT` | Початок розмови | ❌ |
| `STATE_1_DISCOVERY` | Пошук товару (текстовий) | ❌ |
| `STATE_2_VISION` | Обробка фото | ❌ |
| `STATE_3_SIZE_COLOR` | Уточнення розміру/кольору | ❌ |
| `STATE_4_OFFER` | Пропозиція товару | ❌ |
| `STATE_5_PAYMENT_DELIVERY` | Оплата та доставка | ❌ |
| `STATE_6_UPSELL` | Допродаж | ❌ |
| `STATE_7_END` | Завершення | ❌ |
| `STATE_8_COMPLAINT` | Скарга | ✅ L1 |
| `STATE_9_OOD` | Поза доменом | ✅ L1 |

## Інтенти (Intents)

| Intent | Опис | Приклади |
|--------|------|----------|
| `GREETING_ONLY` | Привітання | "Привіт", "Добрий день" |
| `DISCOVERY_OR_QUESTION` | Питання про товари | "Які є костюми?", "Покажіть сукні" |
| `PHOTO_IDENT` | Фото для ідентифікації | [image attached] |
| `SIZE_HELP` | Допомога з розміром | "Який розмір на 128?", "Зріст 140" |
| `COLOR_HELP` | Допомога з кольором | "Є в рожевому?", "Інші кольори" |
| `PAYMENT_DELIVERY` | Оплата/доставка | "Беру", "Оформляємо", "так", "лагуна" (в OFFER) |
| `COMPLAINT` | Скарга | "Верніть гроші", "Погана якість" |
| `THANKYOU_SMALLTALK` | Подяка/завершення | "Дякую", "Подумаю" |
| `OUT_OF_DOMAIN` | Поза доменом | "Яка погода?", "Продай мені біткоін" |
| `UNKNOWN_OR_EMPTY` | Невизначено | "", unclear input |

---

## 🔥 MASTER TRANSITION TABLE

### Rows = Current State, Columns = Detected Intent

| Current State ↓ / Intent → | GREETING | DISCOVERY | PHOTO_IDENT | SIZE_HELP | COLOR_HELP | PAYMENT | COMPLAINT | THANKYOU | OOD | UNKNOWN |
|----------------------------|----------|-----------|-------------|-----------|------------|---------|-----------|----------|-----|---------|
| **STATE_0_INIT** | →S1 agent | →S1 agent | →S2 vision | →S3 agent | →S3 agent | →S5 payment* | →S8 escalation | →S7 end | →S9 agent | →S1 agent |
| **STATE_1_DISCOVERY** | stay agent | →S3 agent | →S2 vision | →S3 agent | →S3 agent | →S4 offer** | →S8 escalation | →S7 end | →S9 agent | stay agent |
| **STATE_2_VISION** | →S4 offer | →S3 agent | stay vision | →S3 agent | →S3 agent | →S4 offer | →S8 escalation | →S7 end | →S9 agent | →S4 offer |
| **STATE_3_SIZE_COLOR** | stay agent | →S4 offer | →S2 vision | stay agent | stay agent | →S4 offer** | →S8 escalation | →S7 end | →S9 agent | stay agent |
| **STATE_4_OFFER** | stay agent | stay agent | →S2 vision | stay offer | stay offer | →S5 payment | →S8 escalation | →S7 end | →S9 agent | stay agent |
| **STATE_5_PAYMENT** | stay payment | stay payment | →S2 vision | stay payment | stay payment | stay payment | →S8 escalation | →S6/S7 | →S9 agent | stay payment |
| **STATE_6_UPSELL** | →S7 end | →S7 end | →S2 vision | →S7 end | →S7 end | →S7 end | →S8 escalation | →S7 end | →S9 agent | →S7 end |
| **STATE_7_END** | →S0 agent | →S1 agent | →S2 vision | →S1 agent | →S1 agent | →S1 agent | →S8 escalation | stay end | →S9 agent | stay end |
| **STATE_8_COMPLAINT** | stay escalation | stay escalation | stay escalation | stay escalation | stay escalation | stay escalation | stay escalation | →S7 end | stay escalation | stay escalation |
| **STATE_9_OOD** | →S0 agent | →S1 agent | →S2 vision | →S1 agent | →S1 agent | →S1 agent | →S8 escalation | →S7 end | stay agent | stay agent |

### Легенда:
- `→SX node` = transition to STATE_X via specified node
- `stay node` = remain in current state, process via node
- `*` = requires products in context
- `**` = requires products in context, otherwise stays
- `escalation` = human handoff

---

## Node Routing Logic (`edges.py`)

### `route_after_intent()`
```
IF should_escalate → "escalation"
IF intent == PHOTO_IDENT → "vision"
IF intent == COMPLAINT → "escalation"
IF intent == PAYMENT_DELIVERY:
    IF current_state in [OFFER, PAYMENT] → "payment"
    IF has_products → "offer"
    ELSE → "agent"
IF intent in [SIZE_HELP, COLOR_HELP] AND has_products → "offer"
ELSE → "agent"
```

### `route_after_vision()`
```
IF has_products → "offer"
IF has_error → "validation"
ELSE → "agent"
```

### `route_after_agent()`
```
IF has_error → "validation"
IF has_products AND NOT in [OFFER, PAYMENT] → "offer"
ELSE → "validation"
```

### `route_after_offer()`
```
IF intent == PAYMENT_DELIVERY → "payment"
ELSE → "validation"
```

---

## Invariants (Must Always Hold)

1. **`has_image` reset**: After `vision_node`, `has_image` MUST be `False`
2. **Valid state**: `current_state` MUST be one of `STATE_0` through `STATE_9`
3. **OFFER → PAYMENT**: In `STATE_4_OFFER`, `PAYMENT_DELIVERY` intent MUST route to `STATE_5_PAYMENT_DELIVERY`
4. **COMPLAINT escalation**: `COMPLAINT` intent MUST always route to `escalation`
5. **Product source**: Product price/color MUST come from Supabase, NOT from LLM

---

## Test Coverage Requirements

Each cell in the transition table MUST have:
1. Unit test for intent detection
2. Integration test for routing
3. E2E test for critical paths (marked with 🔥)

### Critical Paths (E2E required):
- 🔥 `INIT → VISION → OFFER → PAYMENT → END` (photo flow)
- 🔥 `INIT → DISCOVERY → SIZE_COLOR → OFFER → PAYMENT → END` (text flow)
- 🔥 `OFFER → THANKYOU → END` (rejection flow)
- 🔥 `ANY → COMPLAINT → ESCALATION` (complaint flow)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-12-07 | Initial frozen specification |
