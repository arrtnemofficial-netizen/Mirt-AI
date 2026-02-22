# TODO — Workflow execution board

## План
- [x] Створити документ оркестрації workflow для паралельної роботи.
- [x] Додати операційний шаблон для планування задач у `tasks/todo.md`.
- [x] Додати журнал уроків у `tasks/lessons.md`.
- [x] Для кожної нової задачі: копіювати шаблон "Task Card" нижче і заповнювати перед початком.

---

## Active remediation plan — AI логіка, конфлікти, checkpointer

### Task Card: SSOT маршрутизації без дублювання

#### Контекст
- Ціль: прибрати дублювання правил переходів між intent/router/reducer.
- Межі змін: `src/agents/langgraph/nodes/intent.py`, `src/agents/langgraph/routers/intent.py`, `src/agents/langgraph/fsm/transition_reducer.py`, тести.
- Ризики: регресія переходів у payment/escalation flow.

#### План (checkable)
- [ ] Зафіксувати єдиний SSOT переходів (лише reducer/state_machine).
- [ ] Прибрати бізнес-умови переходів з `routers/intent.py`, лишити тільки route mapping.
- [ ] Перевести intent node у режим "класифікація без state transition logic".
- [ ] Додати regression-тести на незмінність критичних переходів.

#### Verification plan
- [ ] `pytest tests/unit/test_router_ssot_consistency.py`
- [ ] `pytest tests/test_fsm_invariants.py`
- [ ] Перевірити, що рішення переходу формується в одному місці.

#### Review (post-implementation)
- Що зроблено:
- Що перевірено:
- Які обмеження лишились:

---

### Task Card: Checkpointer payload minimization (без роздуття state)

#### Контекст
- Ціль: мінімізувати payload checkpoint і прибрати непотрібні поля.
- Межі змін: `src/agents/langgraph/checkpointer.py`, state schema/metadata, unit tests.
- Ризики: втрата полів, потрібних для відновлення діалогу.

#### План (checkable)
- [x] Додати нормалізатор `normalize_checkpoint_state(...)` перед записом.
- [ ] Ввести allowlist ключів для persistence + schema version.
- [x] Обмежити history/messages (останні N + summary marker).
- [ ] Заборонити збереження derived/transient полів (наприклад, дубльованих фаз).
- [x] Додати тест на максимальний розмір payload.

#### Verification plan
- [ ] `pytest tests/unit/test_checkpointer_resilience.py`
- [ ] `pytest tests/unit/test_state_schema_get.py`
- [ ] Новий тест: payload не містить transient/derived ключів.

#### Review (post-implementation)
- Що зроблено:
- Що перевірено:
- Які обмеження лишились:

---

### Task Card: Антиконфліктний quality gate у CI

#### Контекст
- Ціль: автоматично блокувати повернення дублювань та конфліктних правил.
- Межі змін: `tests/static/*`, `scripts/*`, CI команда в `Makefile/pyproject`.
- Ризики: false-positive в статичних перевірках.

#### План (checkable)
- [ ] Додати статичний тест "no duplicated transition rules".
- [ ] Додати контрактний тест checkpoint schema + allowed keys.
- [ ] Додати gate на budget розміру checkpoint payload.
- [ ] Включити нові перевірки в обов'язковий тестовий набір.

#### Verification plan
- [ ] `pytest tests/static/test_state_access_rules.py`
- [ ] `pytest tests/contract/test_model_rules_integrity.py`
- [ ] Запуск нового anti-conflict тесту.

#### Review (post-implementation)
- Що зроблено:
- Що перевірено:
- Які обмеження лишились:

---

## Task Card (template)

### Назва задачі
`<коротка назва>`

### Контекст
- Ціль:
- Межі змін:
- Ризики:

### План (checkable)
- [ ] Крок 1
- [ ] Крок 2
- [ ] Крок 3

### Verification plan
- [ ] Юніт/інтеграційні тести
- [ ] Поведінковий diff до/після (якщо доречно)
- [ ] Логи/інваріанти перевірені

### Review (post-implementation)
- Що зроблено:
- Що перевірено:
- Які обмеження лишились:
