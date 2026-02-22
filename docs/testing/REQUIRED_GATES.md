# Required Test Gates for PR

Ці перевірки є обов'язковими перед merge.

## Smoke gate (SSOT static)

```bash
pytest -q tests/smoke/test_router_intent_ssot_guard.py
```

Fail, якщо router дублює бізнес-keywords з intent-node.

## Contract gate (checkpoint payload)

```bash
pytest -q tests/contract/test_checkpoint_payload_contract.py
```

Fail-threshold:

- `payload_budget_exceeded`
- `missing_schema_version`
- будь-які `unknown_keys`.

## Regression gate (route vs FSM)

```bash
pytest -q tests/regression/test_route_vs_fsm_alignment.py
```

Fail-threshold:

- route vs FSM decision divergence.

## CI інтеграція

Ці три набори тестів підключені в `.github/workflows/ci.yml` в job `critical-gates`.
PR без зеленого статусу цих gate'ів не має merge'итись.
