# Troubleshooting Runbook

**Дата:** 24.12.2025  
**Версія:** 1.0  
**Статус:** ACTIVE

---

## Загальні Принципи

1. **Спочатку перевірте логи** - всі помилки логуються з structured format
2. **Шукайте error_code** - кожна помилка має унікальний код для автоматизації
3. **Дотримуйтесь рекомендацій** - кожна помилка містить конкретні кроки вирішення
4. **Перевіряйте health endpoints** - `/health/ready` показує стан критичних компонентів

---

## Error Codes та Рішення

### CHECKPOINTER Errors

#### CHECKPOINTER_TIMEOUT

**Симптоми:**
- `[VALIDATION:CHECKPOINTER] checkpointer [CHECKPOINTER_TIMEOUT]: Checkpointer validation timeout (10s)`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте SUPABASE_URL:**
   ```bash
   echo $SUPABASE_URL
   # Має бути в форматі: postgresql://user:pass@host:port/dbname
   ```

2. **Перевірте мережеву доступність:**
   ```bash
   # Замініть на ваш реальний URL
   curl -v <SUPABASE_URL>
   ```

3. **Перевірте credentials:**
   ```bash
   echo $SUPABASE_API_KEY | head -c 20
   # Має бути не пустим
   ```

4. **Перевірте PgBouncer:**
   - Якщо використовується PgBouncer, переконайтеся що `prepare_threshold=None` в connection pool
   - Перевірте налаштування пулу: `CHECKPOINTER_POOL_MIN_SIZE=2`, `CHECKPOINTER_POOL_MAX_SIZE=5`

5. **Перевірте timeout:**
   - За замовчуванням timeout = 10s
   - Якщо latency висока, збільште timeout через `CHECKPOINTER_POOL_TIMEOUT_SECONDS`

**Діагностика:**
```bash
# Перевірте connection pool health
curl http://localhost:8080/health/ready | jq '.checks.checkpointer'
```

---

#### CHECKPOINTER_WARMUP_FAILED

**Симптоми:**
- `[VALIDATION:CHECKPOINTER] checkpointer [CHECKPOINTER_WARMUP_FAILED]: Checkpointer warmup failed or timeout`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте що база даних доступна:**
   ```bash
   psql $DATABASE_URL -c "SELECT 1"
   ```

2. **Перевірте що таблиці існують:**
   ```sql
   SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE '%checkpoint%';
   ```

3. **Перевірте connection pool settings:**
   - `CHECKPOINTER_POOL_MIN_SIZE` має бути >= 1
   - `CHECKPOINTER_POOL_MAX_SIZE` має бути > min_size

**Діагностика:**
```bash
# Перевірте логи warmup
grep "Warming up LangGraph" logs/app.log
grep "checkpointer pool opened" logs/app.log
```

---

#### CHECKPOINTER_NOT_INITIALIZED

**Симптоми:**
- `[VALIDATION:CHECKPOINTER] checkpointer [CHECKPOINTER_NOT_INITIALIZED]: Checkpointer not initialized`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте що DATABASE_URL встановлено:**
   ```bash
   echo $DATABASE_URL
   # Або
   echo $DATABASE_URL_POOLER
   ```

2. **Перевірте що checkpointer ініціалізується:**
   - Перевірте логи на помилки ініціалізації
   - Переконайтеся що `langgraph-checkpoint-postgres` package встановлено

3. **Перевірте environment:**
   - В production/staging потрібен явний `DATABASE_URL` або `DATABASE_URL_POOLER`
   - Auto-build з `SUPABASE_API_KEY` вимкнено в production

---

### LLM_PROVIDER Errors

#### LLM_PROVIDER_TIMEOUT

**Симптоми:**
- `[VALIDATION:LLM_PROVIDER] llm_provider [LLM_PROVIDER_TIMEOUT]: LLM provider validation timeout (5s)`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте мережеву доступність до OpenAI API:**
   ```bash
   curl -v https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

2. **Перевірте API key:**
   ```bash
   echo $OPENAI_API_KEY | head -c 10
   # Має починатися з "sk-"
   ```

3. **Перевірте firewall/proxy:**
   - Переконайтеся що вихідні з'єднання до `api.openai.com` дозволені
   - Перевірте proxy settings якщо використовується

**Діагностика:**
```bash
# Перевірте health status
curl http://localhost:8080/health/ready | jq '.checks.llm_provider'
```

---

#### NO_LLM_PROVIDERS_AVAILABLE

**Симптоми:**
- `[VALIDATION:LLM_PROVIDER] llm_provider [NO_LLM_PROVIDERS_AVAILABLE]: No LLM providers available`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте circuit breaker states:**
   ```bash
   # Перевірте логи на circuit breaker states
   grep "circuit" logs/app.log | tail -20
   ```

2. **Перевірте quota:**
   - Відкрийте https://platform.openai.com/account/usage
   - Перевірте що quota не вичерпано

3. **Скиньте circuit breakers:**
   - Якщо всі circuit breakers OPEN, перезапустіть application
   - Circuit breakers автоматично закриються після recovery_timeout (60s)

**Діагностика:**
```bash
# Перевірте preflight check results
grep "preflight" logs/app.log | tail -10
```

---

#### LLM_QUOTA_EXCEEDED (Runtime)

**Симптоми:**
- `[HEALTH_MONITOR] All LLM provider circuit breakers are OPEN`
- Runtime health monitoring виявляє проблему

**Кроки вирішення:**

1. **Перевірте quota status:**
   ```bash
   # Перевірте через OpenAI dashboard
   open https://platform.openai.com/account/usage
   ```

2. **Оновіть billing:**
   - Переконайтеся що billing information актуальна
   - Розгляньте upgrade плану якщо потрібно

3. **Перевірте usage patterns:**
   - Перевірте чи немає несподіваного spike в usage
   - Розгляньте rate limiting якщо потрібно

**Діагностика:**
```bash
# Перевірте runtime health monitoring logs
grep "HEALTH_MONITOR" logs/app.log | tail -20
```

---

### REDIS Errors

#### REDIS_CONNECTION_TIMEOUT

**Симптоми:**
- `[VALIDATION:REDIS] redis [REDIS_CONNECTION_TIMEOUT]: Redis connection timeout (5s)`
- Application не стартує (якщо Redis required)

**Кроки вирішення:**

1. **Перевірте REDIS_URL:**
   ```bash
   echo $REDIS_URL
   # Має бути в форматі: redis://host:port/db або rediss://host:port/db
   ```

2. **Перевірте що Redis server running:**
   ```bash
   redis-cli -u $REDIS_URL ping
   # Має повернути: PONG
   ```

3. **Перевірте мережеву доступність:**
   ```bash
   # Замініть на ваш реальний host:port
   telnet <redis-host> <redis-port>
   ```

4. **Перевірте authentication:**
   - Якщо Redis потребує password, переконайтеся що він вказаний в URL
   - Формат: `redis://:password@host:port/db`

**Діагностика:**
```bash
# Перевірте health endpoint
curl http://localhost:8080/health/ready | jq '.checks.redis'
```

---

#### REDIS_URL_NOT_CONFIGURED

**Симптоми:**
- `[VALIDATION:REDIS] redis [REDIS_URL_NOT_CONFIGURED]: REDIS_URL not configured but Redis is required`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте чи Redis дійсно потрібен:**
   ```bash
   echo $CELERY_ENABLED
   echo $RATE_LIMIT_ENABLED
   # Якщо будь-який = true, Redis required
   ```

2. **Встановіть REDIS_URL:**
   ```bash
   export REDIS_URL="redis://localhost:6379/0"
   # Або для production:
   export REDIS_URL="rediss://user:pass@host:port/db"
   ```

3. **Або вимкніть features що потребують Redis:**
   ```bash
   export CELERY_ENABLED=false
   export RATE_LIMIT_ENABLED=false
   ```

---

### CONFIGURATION Errors

#### CONFIGURATION_VALIDATION_FAILED

**Симптоми:**
- `[PREFLIGHT] Configuration validation failed: ...`
- Application не стартує

**Кроки вирішення:**

1. **Перевірте які саме settings невалідні:**
   ```bash
   # Перевірте логи pre-flight validation
   grep "PREFLIGHT" logs/app.log | tail -20
   ```

2. **Перевірте формат URLs:**
   - `SUPABASE_URL` має починатися з `postgresql://` або `postgres://`
   - `REDIS_URL` має починатися з `redis://` або `rediss://`
   - `PUBLIC_BASE_URL` має починатися з `http://` або `https://`

3. **Перевірте API key formats:**
   - `OPENAI_API_KEY` має починатися з `sk-`
   - `SUPABASE_API_KEY` має бути довгим string (не коротше 10 символів)

4. **Перевірте cross-setting validation:**
   - Якщо `CELERY_ENABLED=true`, то `REDIS_URL` має бути встановлено (не default)

**Діагностика:**
```bash
# Перевірте pre-flight validation results
grep "pre-flight configuration validation" logs/app.log
```

---

## Runtime Health Monitoring

### Pool Exhaustion Warning

**Симптоми:**
- `[HEALTH_MONITOR] Checkpointer pool nearly exhausted: 85.0% (1/10 available)`
- Runtime warning (не блокує application)

**Кроки вирішення:**

1. **Перевірте pool settings:**
   ```bash
   echo $CHECKPOINTER_POOL_MAX_SIZE
   # Розгляньте збільшення якщо часто вичерпується
   ```

2. **Перевірте connection leaks:**
   - Перевірте чи connections правильно закриваються
   - Перевірте чи немає long-running transactions

3. **Моніторте trends:**
   - Якщо utilization зростає, це може вказувати на проблему
   - Перевірте логи на degradation trends

---

### Latency Degradation Warning

**Симптоми:**
- `[HEALTH_MONITOR] Redis latency trending up: +75.0ms over last checks`
- Runtime warning про зростання latency

**Кроки вирішення:**

1. **Перевірте network connectivity:**
   ```bash
   ping <redis-host>
   # Перевірте packet loss та latency
   ```

2. **Перевірте Redis server load:**
   ```bash
   redis-cli -u $REDIS_URL INFO stats
   # Перевірте команди/секунду та інші метрики
   ```

3. **Перевірте connection pool:**
   - Якщо pool вичерпано, latency може зростати
   - Розгляньте збільшення pool size

---

## Health Endpoints

### `/health/ready`

**Призначення:** Readiness probe для Kubernetes/deployment systems

**Використання:**
```bash
curl http://localhost:8080/health/ready
```

**Response format:**
```json
{
  "status": "ready",
  "checks": {
    "checkpointer": {"status": "ok", "error": null},
    "langgraph": {"status": "ok", "error": null},
    "llm_provider": {"status": "ok", "error": null},
    "redis": {"status": "ok", "error": null}
  }
}
```

**Status codes:**
- `200` - всі критичні компоненти готові
- `503` - хоча б один критичний компонент не готовий

---

## Common Scenarios

### Scenario 1: Application не стартує після deploy

1. Перевірте pre-flight validation logs
2. Перевірте `/health/ready` endpoint (якщо доступний)
3. Перевірте structured errors в логах
4. Дотримуйтесь рекомендацій для кожного error_code

### Scenario 2: Application стартує, але повільно працює

1. Перевірте runtime health monitoring logs
2. Перевірте pool utilization warnings
3. Перевірте latency degradation warnings
4. Розгляньте оптимізацію connection pool settings

### Scenario 3: LLM calls fail під час роботи

1. Перевірте circuit breaker states в health monitoring
2. Перевірте quota status
3. Перевірте preflight check warnings
4. Розгляньте fallback стратегію

---

## Escalation

Якщо проблема не вирішена після дотримання всіх кроків:

1. Зберіть structured error logs
2. Зберіть health endpoint responses
3. Зберіть runtime health monitoring logs
4. Створіть issue з error_code та context

---

**Оновлено:** 24 грудня 2025, 23:45 UTC+2

