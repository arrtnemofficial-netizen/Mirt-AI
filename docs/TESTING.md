# 🧪 Testing Strategy (Implementation)

> **Version:** 5.0 (Implementation)  
> **Source:** `tests/`  
> **Updated:** 20 December 2025

---

## 🏗️ Test Pyramid Implementation

### 1. Unit Tests (`tests/unit/`)
Focus on isolated components.

- **FSM logic:** `tests/unit/core/test_state_machine.py`
  - Validates `State.from_string` and transition correctness.
- **Validators:** `tests/unit/services/test_validators.py`
  - Checks if `OrderValidator` correctly catches missing phone numbers.

### 2. Integration Tests (`tests/integration/`)
Focus on component interaction (Requires Docker).

- **ManyChat Pipeline:** `tests/integration/manychat/test_pipeline.py`
  - Mocks Redis, sends `BufferedMessage`, verifies `PipelineResult`.
- **CRM Sync:** `tests/integration/crm/test_snitkix.py`
  - Mocks HTTP interactions with `respx` to test retry logic.

### 3. Golden Data (`tests/data/golden/`)
Contains JSON lines with expected LLM outputs.
- `sizing_golden.jsonl`: "Height 116" -> "Size 116-122".

---

## 🛠️ Conftest Fixtures (`tests/conftest.py`)

- `mock_redis`: `fakeredis` instance for state locking.
- `mock_db`: Async session rollback for Postgres.
- `mock_openai`: Pydantic VCR-like cassette player for deterministic LLM tests.

---

## 📊 Coverage Goals

We enforce coverage via `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
omit = [
    "src/agents/langgraph/visualization.py", # Dev tool
]
```

---
