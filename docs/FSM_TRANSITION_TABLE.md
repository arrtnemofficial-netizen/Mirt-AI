# 🔀 FSM Transition Table (Implementation)

> **Version:** 5.0 (Implementation)  
> **Source:** `src/core/state_machine.py`  
> **Updated:** 20 December 2025

---

## 📊 FSM Implementation Details

The State Machine is defined in `src.core.state_machine` using Python's `StrEnum`.

### 1. States (`State` Enum)

| State Key | Implementation Value | Business Meaning |
|:----------|:---------------------|:-----------------|
| `STATE_0_INIT` | `STATE_0_INIT` | Initial contact / Greeting. |
| `STATE_1_DISCOVERY` | `STATE_1_DISCOVERY` | Identifying user needs (Gender, Height). |
| `STATE_2_VISION` | `STATE_2_VISION` | Processing image input via GPT-4o. |
| `STATE_3_SIZE_COLOR` | `STATE_3_SIZE_COLOR` | Narrowing down SKU selection. |
| `STATE_4_OFFER` | `STATE_4_OFFER` | Presenting final cart proposal. |
| `STATE_5_PAYMENT` | `STATE_5_PAYMENT` | Collecting payment/shipping data. |
| `STATE_6_UPSELL` | `STATE_6_UPSELL` | Post-purchase suggestions. |
| `STATE_7_END` | `STATE_7_END` | Successful closure. |
| `STATE_8_COMPLAINT` | `STATE_8_COMPLAINT` | Escalation to human. |
| `STATE_9_OOD` | `STATE_9_OOD` | Out of Domain / Ignore. |

### 2. Dialog Phases (`DialogPhase`)

The **LangGraph Router** (`master_router`) uses these high-level phases to navigate the FSM:

| Phase String | Target Node | Logic File |
|:-------------|:------------|:-----------|
| `INIT` | `moderation` | `graph.py:171` |
| `DISCOVERY` | `agent` | `graph.py:172` |
| `VISION_DONE` | `agent` | `graph.py:173` |
| `SIZE_COLOR_DONE` | `offer` | `graph.py:176` |
| `OFFER_MADE` | `payment` | `graph.py:177` |
| `COMPLAINT` | `escalation` | `graph.py:181` |

---

## 🔄 Transition Logic (`TRANSITIONS`)

Defined in `src.core.state_machine.py`:

```python
TRANSITIONS = [
    # Init -> Discovery (Greeting)
    Transition(State.STATE_0_INIT, State.STATE_1_DISCOVERY, {Intent.GREETING, Intent.QUESTION}),
    
    # Init -> Vision (Photo)
    Transition(State.STATE_0_INIT, State.STATE_2_VISION, {Intent.PHOTO_IDENT}),
    
    # Discovery -> Size/Color
    Transition(State.STATE_1_DISCOVERY, State.STATE_3_SIZE_COLOR, {Intent.SIZE_HELP, Intent.COLOR_HELP}),
    
    # ... (See file for full list)
]
```

### Self-Correction Loop
Note that `validation_node` does **NOT** change the FSM state. It keeps the user in the *same* state but increments a `retry_count` in `ConversationState`.

---
