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

- If you change Architecture -> Update `docs/ARCHITECTURE.md`.
- If you add Env Vars -> Update `README.md` and `.env.example`.
