# Testing Strategy: The Golden Suite 🛡️

> 📚 **Центральний індекс:** [../DOCUMENTATION.md](../DOCUMENTATION.md)  
> **Статус:** ✅ 924 тести пройдено (9 грудня 2025)

**Trust Nothing. Verify Everything.**

Our testing strategy is designed to catch "Semantic Drift" — when the AI starts behaving differently due to model updates or prompt tweaks.

---

## 1. The Pyramid

- **🏆 Golden Suite (QA)**: Integration & End-to-End. High cost, high confidence.
- **🔍 Unit Tests**: Fast, check logic and prompt structure.
- **📊 Trace Evals**: LLM-as-a-Judge grading real conversations.

---

## 2. Golden Data (`tests/data/golden_data.yaml`)

This file is the **Law**. If a product size mapping changes, it changes here first.

```yaml
scenarios:
  - name: "Strict Size Mapping 119"
    input: "My height is 119 cm"
    expected_output_contains: ["122"]
    forbidden_terms: ["116"]
    rationale: "119cm is closer to 122 than 116 in our sizing."
```

## 3. Worker Testing (`tests/integration/test_workers_integration.py`)

We test the Celery system using `CELERY_TASK_ALWAYS_EAGER=True`.
- **What is tested?**
  - That tasks are routed to correct queues.
  - That idempotency keys are generated correctly.
  - That `llm_usage` is recorded even on failure.
  - That the dispatcher falls back gracefully.

## 4. How to Write a New Test

### Adding a new Business Rule
1. Open `tests/data/golden_data.yaml`.
2. Add a new scenario block.
3. Run `pytest tests/integration/test_agent.py`.
4. If it fails, edit the PROMPT in `data/prompts/states/`.

### verifying Components
Run specific suites:
```bash
# Test the Workers
pytest tests/integration/test_workers_integration.py

# Test the Prompts (Syntax)
pytest tests/unit/test_prompt_basics.py

# Test the Business Logic (Compliance)
pytest tests/unit/test_prompt_compliance.py
```

---

## 5. CI Checks (Ruff + Pytest)

```bash
ruff format .
ruff check .
pytest
```

Note: chaos DB verification tests are skipped unless `SUPABASE_URL` and
`SUPABASE_API_KEY` are set.

---

## 6. Vision & Catalog Tests

Коли змінюєш **master-каталог** (`data/vision/products_master.yaml`) або логіку Vision/каталогу, проганяй ці тести:

```bash
pytest \
  tests/test_vision_health.py \
  tests/test_product_matcher.py \
  tests/test_vision_contract.py -v
```

- `tests/test_vision_health.py` — перевіряє цілісність `data/vision/generated/test_set.json` і `canonical_names.json`.
- `tests/test_product_matcher.py` — нормалізація назв/кольорів, парсинг відповіді Vision.
- `tests/test_vision_contract.py` — контракт `VisionResponse` + критичні правила розрізнення (Лагуна vs Мрія, Ритм vs Каприз, Мерея, тренчі).
