# Contributing to Mirt-AI 🤝

Welcome to the team. To maintain our **"Golden Std"**, please follow these rules strictly.

---

## 1. The Golden Rule of Prompts

**NEVER edit a prompt without adding a test.**
If you change how the bot handles "Returns", you MUST add a "Return Policy" scenario to `tests/data/golden_data.yaml`.

## 2. Code Style

- **Python**: 3.11+
- **Linter**: Ruff (Strict mode).
- **Formatter**: Black compatible.
- **Type Hints**: Required for EVERY function.

## 3. Workflow

1.  **Feature Branch**: `feature/your-feature-name`
2.  **Dev Mode**:
    ```bash
    # Run without Celery (Sync) for easier debugging
    export CELERY_ENABLED=false
    uvicorn src.server.main:app
    ```
3.  **Verification**:
    ```bash
    # MUST PASSS before PR
    pytest
    ```

## 4. Documentation

> **Центральний індекс:** [../DOCUMENTATION.md](../DOCUMENTATION.md)

- Якщо змінюєш архітектуру → Оновлюй `docs/development/DEV_SYSTEM_GUIDE.md` (НЕ `docs/architecture/ARCHITECTURE.md` — він legacy).
- Якщо додаєш Env Vars → Оновлюй `README.md` і `.env.example`.
- Якщо змінюєш FSM логіку → **СПОЧАТКУ** оновлюй `docs/architecture/FSM_TRANSITION_TABLE.md`, потім код.
- Якщо змінюєш промпти → Читай `docs/development/PROMPT_ENGINEERING.md`.
