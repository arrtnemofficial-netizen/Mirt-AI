---
name: "AI Layer Hardening: From 75% to 95% Senior Level"
overview: Підвищити якість AI-шару з 75% до 85-95% senior level через тестування, обробку помилок, observability та валідацію
todos:
  - id: test-support-agent
    content: "Unit тести для run_support (8 тестів: success, message_history, timeout, errors, tokens, edge cases)"
    status: completed
  - id: test-vision-agent
    content: "Unit тести для run_vision (8 тестів: success, no_image_url, CDN, timeout, errors, tokens, invalid_url, base64)"
    status: completed
  - id: test-payment-agent
    content: "Unit тести для run_payment (5 тестів: success, timeout, errors, tokens, missing_fields)"
    status: completed
  - id: test-edge-cases
    content: "Тести для edge cases (7 тестів: None message, empty message, None deps, invalid deps, None history, LLM API error, network error)"
    status: completed
  - id: specific-exceptions
    content: Створити ієрархію специфічних exception типів (AgentError, AgentTimeoutError, AgentValidationError, AgentLLMError, AgentNetworkError)
    status: completed
  - id: retry-logic
    content: Додати retry logic для transient errors з exponential backoff (декоратор @retry_agent_call)
    status: completed
    dependencies:
      - specific-exceptions
  - id: circuit-breaker
    content: Додати circuit breaker для LLM calls (LLMCircuitBreaker клас з failure_threshold, recovery_timeout)
    status: completed
    dependencies:
      - specific-exceptions
  - id: tracing-agent-calls
    content: Додати tracing для agent calls (@trace_agent_call декоратор з spans, tags, logs, Logfire інтеграція)
    status: completed
  - id: agent-metrics
    content: Додати метрики для success rate по агентах (track_agent_metrics функція з success, latency, tokens, error_type)
    status: completed
  - id: alerting-system
    content: Створити alerting систему для критичних помилок (check_agent_health, Celery beat task, Telegram/Slack alerts)
    status: completed
    dependencies:
      - agent-metrics
  - id: validate-deps
    content: Додати валідацію deps перед викликом агента (validate_agent_deps функція для всіх агентів)
    status: completed
    dependencies:
      - specific-exceptions
  - id: validate-message
    content: "Додати валідацію message (validate_message функція: не None, не порожній, max length)"
    status: completed
    dependencies:
      - specific-exceptions
  - id: validate-image-url
    content: "Додати валідацію image_url для vision agent (validate_image_url функція: HTTP(S) URL, max length)"
    status: completed
    dependencies:
      - specific-exceptions
---

# AI Layer Hardening: Від 75% до 95% Senior Level

## Мета

Підвищити якість AI-шару з **75% до 95% senior level** через:

1. Тестування агентів (50% → 80%)
2. Обробка помилок (80% → 90%)
3. Observability (75% → 85%)
4. Валідація вхідних даних (70% → 85%)

---

## БЛОК 1: Тестування агентів (50% → 80%)

### Задача 1.1: Unit тести для `run_support`

**Файл**: `tests/unit/test_support_agent.py` (новий)**Тести**:

1. `test_run_support_success` - успішний виклик з валідними даними
2. `test_run_support_with_message_history` - виклик з історією повідомлень
3. `test_run_support_timeout` - обробка TimeoutError
4. `test_run_support_generic_error` - обробка загальних помилок
5. `test_run_support_extracts_tokens` - витягнення токенів з `result.usage`
6. `test_run_support_handles_none_usage` - обробка `None` usage
7. `test_run_support_handles_empty_usage` - обробка порожнього usage
8. `test_run_support_logs_usage` - перевірка логування usage

**Моки**:

- Mock `Agent.run()` з `AgentRunResult`
- Mock `RunUsage` з різними сценаріями
- Mock `log_llm_usage_best_effort`

**Критерії успіху**:

- ✅ Всі тести проходять
- ✅ Coverage для `run_support` > 80%
- ✅ Тести покривають edge cases

**Ризики**:

- PydanticAI Agent важко мокати (може знадобитися інтеграційний тест)
- Мітигація: використати `unittest.mock.patch` для `agent.run`

---

### Задача 1.2: Unit тести для `run_vision`

**Файл**: `tests/unit/test_vision_agent.py` (новий)**Тести**:

1. `test_run_vision_success` - успішне розпізнавання фото
2. `test_run_vision_no_image_url` - обробка відсутності `image_url`
3. `test_run_vision_private_cdn_download` - завантаження з приватного CDN
4. `test_run_vision_timeout` - обробка TimeoutError
5. `test_run_vision_generic_error` - обробка загальних помилок
6. `test_run_vision_extracts_tokens` - витягнення токенів
7. `test_run_vision_handles_invalid_image_url` - обробка невалідного URL
8. `test_run_vision_base64_conversion` - конвертація в base64

**Моки**:

- Mock `httpx.AsyncClient` для завантаження зображень
- Mock `Agent.run()` з `VisionResponse`
- Mock `_download_image_as_base64`

**Критерії успіху**:

- ✅ Всі тести проходять
- ✅ Coverage для `run_vision` > 80%
- ✅ Тести покривають edge cases (CDN, timeout, errors)

**Ризики**:

- Завантаження зображень потребує реальних HTTP запитів
- Мітигація: мокати `httpx.AsyncClient` повністю

---

### Задача 1.3: Unit тести для `run_payment`

**Файл**: `tests/unit/test_payment_agent.py` (новий)**Тести**:

1. `test_run_payment_success` - успішна обробка платежу
2. `test_run_payment_timeout` - обробка TimeoutError
3. `test_run_payment_generic_error` - обробка загальних помилок
4. `test_run_payment_extracts_tokens` - витягнення токенів
5. `test_run_payment_handles_missing_fields` - обробка відсутніх полів

**Моки**:

- Mock `Agent.run()` з `PaymentResponse`
- Mock `RunUsage`

**Критерії успіху**:

- ✅ Всі тести проходять
- ✅ Coverage для `run_payment` > 80%

---

### Задача 1.4: Тести для edge cases

**Файл**: `tests/unit/test_agent_edge_cases.py` (новий)**Тести**:

1. `test_agent_handles_none_message` - обробка `None` message
2. `test_agent_handles_empty_message` - обробка порожнього message
3. `test_agent_handles_none_deps` - обробка `None` deps
4. `test_agent_handles_invalid_deps` - обробка невалідних deps
5. `test_agent_handles_none_message_history` - обробка `None` message_history
6. `test_agent_handles_llm_api_error` - обробка помилок LLM API
7. `test_agent_handles_network_error` - обробка мережевих помилок

**Критерії успіху**:

- ✅ Всі edge cases покриті тестами
- ✅ Агенти не падають на невалідних вхідних даних

---

## БЛОК 2: Обробка помилок (80% → 90%)

### Задача 2.1: Специфічні exception типи

**Файл**: `src/agents/pydantic/exceptions.py` (новий)**Створити ієрархію exceptions**:

```python
class AgentError(Exception):
    """Base exception for agent errors."""
    pass

class AgentTimeoutError(AgentError):
    """Agent execution timeout."""
    pass

class AgentValidationError(AgentError):
    """Agent input validation error."""
    pass

class AgentLLMError(AgentError):
    """LLM API error."""
    pass

class AgentNetworkError(AgentError):
    """Network error during agent execution."""
    pass
```

**Змінити обробку помилок**:

- `src/agents/pydantic/support_agent.py` - використати специфічні exceptions
- `src/agents/pydantic/vision_agent.py` - використати специфічні exceptions
- `src/agents/pydantic/payment_agent.py` - використати специфічні exceptions

**Критерії успіху**:

- ✅ Ієрархія exceptions створена
- ✅ Всі агенти використовують специфічні exceptions
- ✅ Логування покращено (різні рівні для різних помилок)

**Ризики**:

- Може зламати існуючий код, який очікує `Exception`
- Мітигація: зберегти backward compatibility через `except AgentError as e:`

---

### Задача 2.2: Retry logic для transient errors

**Файл**: `src/agents/pydantic/retry.py` (новий)**Створити retry декоратор**:

```python
@retry_agent_call(
    max_retries=3,
    retry_on=(AgentNetworkError, AgentLLMError),
    backoff=exponential_backoff(initial=1.0, max=10.0),
)
async def run_support(...):
    ...
```

**Логіка retry**:

- Retry тільки для transient errors (network, rate limits)
- Exponential backoff між спробами
- Логування кожної спроби
- Метрики для retry rate

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - додати retry декоратор
- `src/agents/pydantic/vision_agent.py` - додати retry декоратор
- `src/agents/pydantic/payment_agent.py` - додати retry декоратор

**Критерії успіху**:

- ✅ Retry logic працює для transient errors
- ✅ Не retry для permanent errors (validation, timeout)
- ✅ Метрики для retry rate збираються

**Ризики**:

- Може збільшити latency при retry
- Мітигація: обмежити max_retries та backoff

---

### Задача 2.3: Circuit breaker для LLM calls

**Файл**: `src/agents/pydantic/circuit_breaker.py` (новий)**Створити circuit breaker**:

```python
class LLMCircuitBreaker:
    """Circuit breaker for LLM API calls."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        ...
    
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        ...
```

**Інтеграція**:

- Використати існуючий `CircuitBreaker` з `src/integrations/manychat/async_service.py` як основу
- Додати circuit breaker для кожного агента
- Метрики для circuit breaker state (open/closed/half-open)

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - обгорнути `agent.run()` в circuit breaker
- `src/agents/pydantic/vision_agent.py` - обгорнути `agent.run()` в circuit breaker
- `src/agents/pydantic/payment_agent.py` - обгорнути `agent.run()` в circuit breaker

**Критерії успіху**:

- ✅ Circuit breaker працює для LLM calls
- ✅ Метрики для circuit breaker state збираються
- ✅ Graceful degradation при open circuit

**Ризики**:

- Може блокувати легітимні запити при false positives
- Мітигація: налаштувати threshold та recovery timeout

---

## БЛОК 3: Observability (75% → 85%)

### Задача 3.1: Tracing для agent calls

**Файл**: `src/agents/pydantic/tracing.py` (новий)**Створити tracing декоратор**:

```python
@trace_agent_call(agent_name="support")
async def run_support(...):
    ...
```

**Логіка tracing**:

- Створити span для кожного agent call
- Додати tags: `agent_name`, `session_id`, `model`, `tokens`
- Додати logs: start, success, error
- Інтегрувати з Logfire (якщо доступний)

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - додати tracing декоратор
- `src/agents/pydantic/vision_agent.py` - додати tracing декоратор
- `src/agents/pydantic/payment_agent.py` - додати tracing декоратор

**Критерії успіху**:

- ✅ Tracing працює для всіх agent calls
- ✅ Spans містять корисну інформацію
- ✅ Інтеграція з Logfire (якщо доступний)

**Ризики**:

- Може додати overhead до latency
- Мітигація: використати async tracing, не блокувати execution

---

### Задача 3.2: Метрики для success rate по агентах

**Файл**: `src/agents/pydantic/metrics.py` (новий)**Створити метрики**:

```python
def track_agent_metrics(
    agent_name: str,
    success: bool,
    latency_ms: float,
    tokens_input: int = 0,
    tokens_output: int = 0,
    error_type: str | None = None,
):
    """Track agent execution metrics."""
    track_metric(f"agent_{agent_name}_success", 1 if success else 0)
    track_metric(f"agent_{agent_name}_latency_ms", latency_ms)
    track_metric(f"agent_{agent_name}_tokens_input", tokens_input)
    track_metric(f"agent_{agent_name}_tokens_output", tokens_output)
    if error_type:
        track_metric(f"agent_{agent_name}_error", 1, {"error_type": error_type})
```

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - додати виклик `track_agent_metrics`
- `src/agents/pydantic/vision_agent.py` - додати виклик `track_agent_metrics`
- `src/agents/pydantic/payment_agent.py` - додати виклик `track_agent_metrics`

**Критерії успіху**:

- ✅ Метрики збираються для всіх агентів
- ✅ Success rate рахується правильно
- ✅ Метрики доступні в observability системі

**Ризики**:

- Може додати overhead до execution
- Мітигація: використати async logging, не блокувати execution

---

### Задача 3.3: Alerting на критичні помилки

**Файл**: `src/agents/pydantic/alerting.py` (новий)**Створити alerting систему**:

```python
def check_agent_health(agent_name: str) -> bool:
    """Check if agent is healthy based on recent metrics."""
    recent_errors = get_recent_errors(agent_name, window_minutes=5)
    if recent_errors > ERROR_THRESHOLD:
        send_alert(f"Agent {agent_name} has high error rate: {recent_errors}")
        return False
    return True
```

**Інтеграція**:

- Використати існуючий `track_metric` для збору метрик
- Додати перевірку health check в Celery beat task
- Відправляти alerts через Telegram/Slack (якщо налаштовано)

**Критерії успіху**:

- ✅ Alerts відправляються при високому error rate
- ✅ Alerts відправляються при circuit breaker open
- ✅ Alerts відправляються при timeout spike

**Ризики**:

- Може створити spam alerts
- Мітигація: налаштувати thresholds та rate limiting для alerts

---

## БЛОК 4: Валідація вхідних даних (70% → 85%)

### Задача 4.1: Перевірка deps перед викликом агента

**Файл**: `src/agents/pydantic/validation.py` (новий)**Створити валідацію deps**:

```python
def validate_agent_deps(deps: AgentDeps, agent_type: str) -> None:
    """Validate AgentDeps before agent execution."""
    if not deps:
        raise AgentValidationError("deps cannot be None")
    if not deps.session_id:
        raise AgentValidationError("deps.session_id is required")
    if agent_type == "vision" and not deps.image_url:
        raise AgentValidationError("deps.image_url is required for vision agent")
    ...
```

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - додати `validate_agent_deps(deps, "support")`
- `src/agents/pydantic/vision_agent.py` - додати `validate_agent_deps(deps, "vision")`
- `src/agents/pydantic/payment_agent.py` - додати `validate_agent_deps(deps, "payment")`

**Критерії успіху**:

- ✅ Валідація працює для всіх агентів
- ✅ Помилки валідації логуються правильно
- ✅ Агенти не падають на невалідних deps

**Ризики**:

- Може зламати існуючий код, який передає невалідні deps
- Мітигація: додати тести для валідації, перевірити всі виклики агентів

---

### Задача 4.2: Валідація message (не None, не порожній)

**Файл**: `src/agents/pydantic/validation.py` (оновлений)**Додати валідацію message**:

```python
def validate_message(message: str | None) -> str:
    """Validate and normalize message."""
    if message is None:
        raise AgentValidationError("message cannot be None")
    message = message.strip()
    if not message:
        raise AgentValidationError("message cannot be empty")
    if len(message) > 10000:  # Reasonable limit
        raise AgentValidationError(f"message too long: {len(message)} chars (max 10000)")
    return message
```

**Змінити агенти**:

- `src/agents/pydantic/support_agent.py` - додати `validate_message(message)` на початку
- `src/agents/pydantic/vision_agent.py` - додати `validate_message(message)` на початку
- `src/agents/pydantic/payment_agent.py` - додати `validate_message(message)` на початку

**Критерії успіху**:

- ✅ Валідація message працює для всіх агентів
- ✅ Помилки валідації логуються правильно
- ✅ Агенти не падають на невалідних message

**Ризики**:

- Може зламати існуючий код, який передає невалідні message
- Мітигація: додати тести для валідації, перевірити всі виклики агентів

---

### Задача 4.3: Перевірка image_url для vision agent

**Файл**: `src/agents/pydantic/validation.py` (оновлений)**Додати валідацію image_url**:

```python
def validate_image_url(image_url: str | None) -> str:
    """Validate image URL for vision agent."""
    if not image_url:
        raise AgentValidationError("image_url is required for vision agent")
    image_url = image_url.strip()
    if not image_url:
        raise AgentValidationError("image_url cannot be empty")
    if not (image_url.startswith("http://") or image_url.startswith("https://")):
        raise AgentValidationError(f"image_url must be a valid HTTP(S) URL: {image_url}")
    if len(image_url) > 2048:  # Reasonable limit
        raise AgentValidationError(f"image_url too long: {len(image_url)} chars (max 2048)")
    return image_url
```

**Змінити vision agent**:

- `src/agents/pydantic/vision_agent.py` - додати `validate_image_url(deps.image_url)` на початку

**Критерії успіху**:

- ✅ Валідація image_url працює для vision agent
- ✅ Помилки валідації логуються правильно
- ✅ Vision agent не падає на невалідних image_url

**Ризики**:

- Може зламати існуючий код, який передає невалідні image_url
- Мітигація: додати тести для валідації, перевірити всі виклики vision agent

---

## Підсумок та порядок виконання

### Пріоритет виконання

**Фаза 1: Критичні покращення (1-2 тижні)**

1. Задача 4.1-4.3: Валідація вхідних даних (запобігає падінням)
2. Задача 2.1: Специфічні exception типи (покращує обробку помилок)
3. Задача 1.1-1.3: Unit тести для агентів (покриває базові сценарії)

**Фаза 2: Надійність (2-3 тижні)**

4. Задача 2.2: Retry logic (покращує стійкість до transient errors)
5. Задача 2.3: Circuit breaker (захищає від каскадних відмов)
6. Задача 1.4: Тести для edge cases (покриває крайні випадки)

**Фаза 3: Observability (1-2 тижні)**

7. Задача 3.1: Tracing для agent calls (дозволяє дебажити проблеми)
8. Задача 3.2: Метрики для success rate (моніторинг здоров'я системи)
9. Задача 3.3: Alerting на критичні помилки (швидке реагування)

### Загальні критерії успіху

**Тестування**:

- ✅ Coverage для всіх агентів > 80%
- ✅ Всі edge cases покриті тестами
- ✅ Інтеграційні тести для критичних шляхів

**Обробка помилок**:

- ✅ Специфічні exception типи для всіх помилок
- ✅ Retry logic працює для transient errors
- ✅ Circuit breaker захищає від каскадних відмов

**Observability**:

- ✅ Tracing працює для всіх agent calls
- ✅ Метрики збираються для всіх агентів
- ✅ Alerts налаштовані для критичних помилок

**Валідація**:

- ✅ Всі вхідні дані валідуються перед викликом агентів
- ✅ Помилки валідації логуються правильно
- ✅ Агенти не падають на невалідних вхідних даних

### Метрики успіху

**До покращень**:

- Тестування: 50%
- Обробка помилок: 80%
- Observability: 75%
- Валідація: 70%
- **Загальна оцінка: 75%**

**Після покращень**:

- Тестування: 80%+
- Обробка помилок: 90%+
- Observability: 85%+
- Валідація: 85%+
- **Загальна оцінка: 85-95%**

### Ризики та мітигація

**Загальні ризики**:

1. **Регресії в існуючому коді**

- Мітигація: запускати всі існуючі тести після кожної зміни
- Мітигація: покрокове впровадження з можливістю rollback

2. **Збільшення latency**

- Мітигація: використовувати async операції для observability
- Мітигація: обмежити retry attempts та backoff

3. **Складність підтримки**

- Мітигація: додати детальну документацію
- Мітигація: використовувати стандартні паттерни (retry, circuit breaker)

4. **False positives в alerts**

- Мітигація: налаштувати thresholds на основі історичних даних
- Мітигація: додати rate limiting для alerts

### Документація

**Створити документацію**:

- `docs/ai_agents/error_handling.md` - як обробляються помилки
- `docs/ai_agents/observability.md` - як працює observability
- `docs/ai_agents/validation.md` - правила валідації вхідних даних
- `docs/ai_agents/testing.md` - як тестувати агенти

---

## Висновок

Цей план переводить AI-шар з **75% до 85-95% senior level** через систематичне покращення:

1. **Тестування** - покриття всіх сценаріїв та edge cases
2. **Обробка помилок** - специфічні exceptions, retry, circuit breaker
3. **Observability** - tracing, метрики, alerting
4. **Валідація** - перевірка всіх вхідних даних

Після виконання плану система стане:

- ✅ Більш надійною (менше падінь)
- ✅ Більш спостережуваною (легше дебажити)
- ✅ Більш тестованою (легше рефакторити)
- ✅ Більш production-ready (готово до масштабування)