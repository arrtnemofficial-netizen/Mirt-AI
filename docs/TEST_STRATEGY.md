# Test Strategy (Mirt-AI)

## Purpose
Keep the release velocity high while making regressions impossible to hide.

## Test Tiers

- **Critical Gates**: must be green for every PR and release.
  - `ruff check --select F821,F401 src/ tests/`
  - `python scripts/check_ai_smell_comments.py`
  - `pytest -q tests/smoke/test_graph_builds.py tests/unit/test_payment_node.py tests/test_vision_contract.py`
  - `pytest -q tests/unit/test_validation_node.py tests/unit/test_prompt_compliance.py`
  - `pytest -q tests/security/test_auth_and_rate_limiting.py tests/scenario/test_state5_scenarios.py tests/test_fsm_invariants.py`
  - `pytest -q tests/unit/test_prompt_contract_snapshot.py`

- **Extended Gates**: run on PR labels / nightly window.
  - full `pytest -q tests/`
  - `pytest -q tests/unit/test_vision_async_lifecycle.py tests/unit/test_vision_node_fallbacks.py tests/unit/test_guardrails_loop_detector.py`
  - contract/security deep checks and load-stability probes.

- **Release Candidate Gates**: run on protected branch before rollout.
  - full project test suite + async/vision stress probes
  - smoke + state-fidelity checks with canary metrics enabled.

## Failure Policy

If any critical gate fails:
1. Block merge/release.
2. Roll back to last green commit.
3. Add/adjust regression test(s) before re-running gates.

## CI Mapping

- `critical` job: only Critical Gates.
- `test` job: Extended Gates.
- `security` job: non-blocking until RC, then monitored.

## Runtime Safety Gates

- Any fallback in high-risk paths must emit:
  - `fallback_triggered`
  - `fallback_reason`
  - `session_id`
  - `state`
  - `node`

- Any change in route/intent behavior in `STATE_5` must include a scenario test.

## Comment Style Policy

- Comments must explain invariants, edge cases, or non-obvious constraints.
- Avoid emotional, marketing, or persona-driven comment markers.
- Prohibited markers in production code comments:
  - `SENIOR-LEVEL`
  - `ЗАЛІЗОБЕТОННО`
  - `AI wrote this`
