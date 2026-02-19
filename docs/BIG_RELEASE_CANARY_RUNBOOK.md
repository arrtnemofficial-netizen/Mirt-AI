# Big Release Canary Runbook (Mirt-AI)

Last updated: 2026-02-12

## Scope
One large release with guarded rollout and instant rollback via feature flags.

## Invariants
- Public HTTP contracts stay backward compatible.
- `OUTPUT_CONTRACT` fields are not removed or renamed.
- Additive metadata only:
  - `metadata.transition_reason`
  - `metadata.transition_source`
  - `metadata.payment_sub_phase`

## Feature Flags (release control)
- `FSM_STATE5_STRICT_MODE=true`
- `PAYMENT_DELEGATE_V2=true` (deprecated, ignored at runtime)
- `ROUTER_SCHEMA_TOLERANT=true`
- `RATE_LIMITER_SLOWAPI_ENABLED=false` (enable only in canary)
- `STRICT_EXCEPTION_POLICY=true`

## Pre-Release Checklist
1. Freeze risky changes 3 days before production rollout.
2. Build release candidate and run full critical verification:
   - `python -m ruff check --select F821,F401 src/ tests/`
   - `python -m pytest -q tests/smoke/test_graph_builds.py`
   - `python -m pytest -q tests/unit/test_payment_node.py tests/test_vision_contract.py`
   - `python -m pytest -q tests/unit/test_validation_node.py tests/unit/test_prompt_compliance.py`
   - `python -m pytest -q tests/security/test_auth_and_rate_limiting.py tests/scenario/test_state5_scenarios.py tests/test_fsm_invariants.py`
3. Capture baseline metrics (24h):
   - `P0 runtime exceptions` in routing/payment/vision
   - payment and vision fallback rates
   - `stuck STATE_5` rate
   - escalation rate due to technical errors

## Canary Rollout
1. Stage 1: 5% traffic, 24h.
2. Stage 2: 25% traffic, 24h.
3. Stage 3: 50% traffic, 24h.
4. Stage 4: 100% traffic.

At each stage, gate on:
- no increase of critical exceptions
- no increase of stuck `STATE_5_PAYMENT_DELIVERY`
- no increase of technical escalations
- stable fallback rate (payment/vision)

## Rollback Plan (no code deploy)
If any stage fails, immediately flip flags to legacy-safe behavior:
1. `FSM_STATE5_STRICT_MODE=false`
2. `PAYMENT_DELEGATE_V2=false` (no runtime effect, kept for rollback checklist compatibility)
3. `ROUTER_SCHEMA_TOLERANT=true` (keep tolerance on)
4. `RATE_LIMITER_SLOWAPI_ENABLED=false`
5. `STRICT_EXCEPTION_POLICY=true` (keep observability on)

Then:
1. Re-check webhook/API auth and payment smoke flow.
2. Keep traffic at current stage or return to previous stable stage.
3. Open incident follow-up with exact metric deltas and first-error timestamps.

## Post-Release Exit Criteria
- 100% traffic reached.
- No sustained increase in critical errors.
- No sustained increase in `STATE_5` loops.
- Critical suites remain green on main branch.
