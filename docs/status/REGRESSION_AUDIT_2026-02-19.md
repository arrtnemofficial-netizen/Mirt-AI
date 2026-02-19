# Regression Audit (2026-02-19)

## Scope
Поглиблена перевірка після останніх великих комітів із акцентом на **ідеальність AI-шару**: промпти, контракти, анти-smell контроль, vision-контракт, плюс базові системні регресії.

## Implemented gate system
- Додано/оновлено `scripts/run_regression_gate.py`.
- Додано `make regression-gate` і `make ai-layer-gate`.
- Новий режим: `--ai-layer-only`.

### AI-layer gates (обов'язкові)
1. `python scripts/check_ai_smell_comments.py`
2. `pytest -q tests/unit/test_prompt_compliance.py`
3. `pytest -q tests/unit/test_prompt_contract_snapshot.py`
4. `pytest -q tests/test_vision_contract.py`

### Cross-layer regression gates
1. `ruff check src tests`
2. `pytest -q tests/smoke/test_graph_builds.py`
3. `pytest -q tests/unit/test_payment_node.py tests/scenario/test_state5_scenarios.py`

### Stability guards
- Перевірка Python baseline (`>=3.11`).
- Перевірка узгодженості critical dependency pins між `pyproject.toml` і `requirements.txt`.
- Інфраструктурні обмеження (proxy / package resolver) маркуються як `warn`, а не як псевдо-регресія коду.

## Findings
1. **Dependency drift** виправлено вирівнюванням pinned версій.
2. **AI-layer gate** виділено в окремий режим, щоб перевіряти саме якість AI-шару незалежно від решти системи.
3. Поточне локальне середовище обмежене (Python 3.10, proxy 403), тому повний verdict треба підтверджувати в CI на Python 3.11/3.12.

## Next actions
1. Додати `make ai-layer-gate` у CI як required status check.
2. Тримати prompt/vision зміни тільки разом із відповідними AI-layer тестами.
3. Винести lint cleanup в окремий PR без функціональних змін.
