# AI Layer, Logic, and Prompts Breakdown (Synced)

Last synced: 2026-02-12

## Scope
This document reflects **current implementation** for:
- LangGraph routing and node orchestration
- FSM transition reducer and STATE_5 strict behavior
- Payment flow sub-phases and prompt usage
- Prompt-code consistency expectations

## Runtime SSOT
- FSM states and transitions: `src/core/state_machine.py`
- Transition decision engine: `src/agents/langgraph/fsm/transition_reducer.py`
- Final state reconciliation after LLM call: `src/agents/langgraph/nodes/handlers/transition_handler.py`
- Router boundary schema normalization: `src/agents/langgraph/routers/base.py`

## STATE_5 Determinism (Current)
- Feature flag: `FSM_STATE5_STRICT_MODE=true` (default)
- In `STATE_5_PAYMENT_DELIVERY`, short acknowledgements (`так/да/ок/дякую`) are treated as payment continuation when payment proof is not received.
- Explicit refusal/cancel markers (`скасувати/відміна/не хочу/...`) are separated from short acknowledgements and can transition to closure flow.
- Transition source tracking:
  - `intent_node` when deterministic intent is used
  - `llm` when LLM metadata intent is used
  - `override` for hard overrides

## Additive Internal Metadata (Current)
State metadata now carries additive fields:
- `transition_reason`
- `transition_source` (`intent_node | llm | override`)
- `payment_sub_phase`

These fields are internal observability fields and do not break public API contracts.

## Payment Sub-Phase Alignment
- Payment helper no longer forces `dialog_phase=WAITING_FOR_PAYMENT_PROOF` unconditionally.
- `dialog_phase` is derived from `payment_sub_phase` mapping:
  - `REQUEST_DATA -> WAITING_FOR_DELIVERY_DATA`
  - `CONFIRM_DATA -> WAITING_FOR_PAYMENT_METHOD`
  - `SHOW_PAYMENT -> WAITING_FOR_PAYMENT_PROOF`
  - `THANK_YOU -> UPSELL_OFFERED`

## Prompt Layer (STATE_5)
Synced prompt files:
- `data/prompts/states/STATE_5_PAYMENT_DELIVERY.md`
- `data/prompts/states/STATE_5_PAYMENT_DELIVERY_REQUEST.md`
- `data/prompts/states/STATE_5_PAYMENT_DELIVERY_CONFIRM.md`
- `data/prompts/states/STATE_5_PAYMENT_DELIVERY_PAYMENT.md`
- `data/prompts/states/STATE_5_PAYMENT_DELIVERY_THANKS.md`

Current alignment rules:
- Short acknowledgements in STATE_5 must stay in payment flow.
- Explicit cancel/refusal can end payment flow.
- No directive should allow completion without payment proof unless explicit refusal path is chosen.

## Feature Flags Added
In `src/conf/config.py`:
- `FSM_STATE5_STRICT_MODE=true`
- `PAYMENT_DELEGATE_V2=true` (deprecated, ignored at runtime; removal planned)
- `ROUTER_SCHEMA_TOLERANT=true`
- `RATE_LIMITER_SLOWAPI_ENABLED=false`
- `STRICT_EXCEPTION_POLICY=true`

## Prompt Compliance Tests
Prompt-code consistency checks are enforced in:
- `tests/unit/test_prompt_compliance.py`

The suite verifies:
- STATE_5 short-ack behavior is documented
- Explicit cancel markers are documented
- Contradictory finish-without-proof directives are absent

## Runtime Regression Coverage
Critical regressions are covered by tests:
- Router minimal state tolerance
- Vision local variable initialization safety
- Payment delegate signature/fallback safety
- Validation phase auto-normalization safety

Primary test files:
- `tests/smoke/test_graph_builds.py`
- `tests/test_vision_contract.py`
- `tests/unit/test_payment_node.py`
- `tests/unit/test_validation_node.py`
