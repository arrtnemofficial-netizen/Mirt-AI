# ?? Testing Strategy (Implementation)

> **Version:** 5.0 (Implementation)  
> **Source:** `tests/`  
> **Updated:** 20 December 2025

---

## ??? Test Pyramid Implementation

### 1. Core Tests (flat `tests/`)
No mocks allowed. No env required.

- Example: `pytest tests`

### 2. Live Tests (`live_test/`)
Real services only. Env required.

- Example: `pytest live_test`

### 3. Golden Data (flat `tests/`)
Golden flows are stored alongside tests.

---

## ??? Conftest Fixtures (`tests/conftest.py`)

- `mock_redis`: `fakeredis` instance for state locking.
- `mock_db`: Async session rollback for Postgres.
- `mock_openai`: Pydantic VCR-like cassette player for deterministic LLM tests.

---

## ?? Coverage Goals

We enforce coverage via `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
omit = [
    "src/agents/langgraph/visualization.py", # Dev tool
]
```

---
