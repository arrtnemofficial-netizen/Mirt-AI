# 👨‍💻 Developer System Guide (Implementation)

> **Version:** 5.0 (Implementation)  
> **Updated:** 20 December 2025

---

## 🚀 Development Environment

### 1. Prerequisites
- **Python:** 3.11+ (Strict requirement due to `StrEnum` usage).
- **Poetry/Pip:** `requirements.txt` is the SSOT.
- **Docker:** For local Redis/Postgres.

### 2. Local Setup
```bash
# Clone
git clone https://github.com/mirt-ua/mirt-ai.git
cd mirt-ai

# Venv
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install deps
pip install -r requirements.txt
```

### 3. Running Services (Local)

**Terminal 1: FastAPI**
```bash
# --reload is key for DX
uvicorn src.server.main:app --reload --port 8000
```

**Terminal 2: Celery Worker**
```bash
# Run with 'pool=solost' on Windows to avoid spawning issues
celery -A src.workers.celery_app worker -l info --pool=solost
```

**Terminal 3: Celery Beat**
```bash
celery -A src.workers.celery_app beat -l info
```

---

## 🧪 Testing Workflow used in CI

Based on `tests/` folder structure.

### Core Tests
```bash
# No mocks; no env required
pytest tests
```

### Live Tests
Requires real services and env variables.
```bash
pytest live_test
```

### Formatting (Ruff)
We use **Ruff** for both linting and formatting. configuration is in `pyproject.toml`.
```bash
# Check
ruff check .
# Fix
ruff check . --fix
# Format
ruff format .
```

---

## 🐛 Debugging Tips

### LangGraph Inspection
Use `invoke_graph` helper from `src.agents.langgraph.graph`:

```python
from src.agents.langgraph.graph import invoke_graph

# This allows you to step through the graph locally
res = await invoke_graph(
    session_id="debug_session_1",
    messages=[{"role": "user", "content": "Hello"}]
)
print(res["messages"][-1])
```

### Celery Eager Mode
Set `CELERY_EAGER=true` in `.env` to run tasks synchronously in the same process. This is useful for debugging breakpoints in PyCharm/VSCode.

---
