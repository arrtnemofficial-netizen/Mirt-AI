# Startup Logs Reference

**Дата:** 24.12.2025  
**Версія:** 1.0  
**Призначення:** Документація про очікувані логи при успішному startup

---

## Успішний Startup - Expected Logs

При успішному startup додаток має вивести наступні логи в правильному порядку:

### 1. Container/Server Startup
```
[inf] Starting Container
[inf] Starting server on port 8080...
[err] INFO:     Started server process [1]
[err] INFO:     Waiting for application startup.
```

### 2. Application Initialization
```
[inf] Building production graph...
[inf] Starting MIRT AI Webhooks server
```

### 3. LangGraph Warmup
```
[inf] Warming up LangGraph (this may take 10-20 seconds on first deploy)...
[inf] AsyncPostgresSaver checkpointer initialized successfully
[inf] Production graph built with HITL interrupt_before=['payment']
[inf] Opening AsyncPostgresSaver checkpointer pool...
[inf] AsyncPostgresSaver checkpointer pool opened successfully
[inf] AsyncPostgresSaver checkpointer initialized and verified (async methods available)
[inf] LangGraph warmed up successfully!
```

### 4. Critical Components Validation
```
[inf] Validating critical components...
[inf] All critical components validated successfully
```

### 5. Application Ready
```
[err] INFO:     Application startup complete.
[err] INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

---

## Опціональні Компоненти

### Redis (якщо enabled)
```
[inf] Redis rate limiter connected
```
або
```
[inf] Using Redis for distributed rate limiting
```

### Telegram (якщо enabled)
```
[inf] Telegram webhook registered: https://your-domain.com/webhooks/telegram
```

---

## Fail-Fast Scenarios

Якщо критичний компонент не готовий, додаток **НЕ СТАРТУЄ** (fail-fast):

### Checkpointer Failed
```
[inf] Validating critical components...
[crit] CRITICAL: Checkpointer validation failed: Checkpointer warmup failed or timeout
[crit] Startup validation failed. Critical components not ready: checkpointer
[crit] Validation details: {...}
```
**Результат:** RuntimeError, додаток не стартує

### LangGraph Failed
```
[inf] Validating critical components...
[crit] CRITICAL: LangGraph validation failed: LangGraph graph not initialized
[crit] Startup validation failed. Critical components not ready: langgraph
```
**Результат:** RuntimeError, додаток не стартує

### LLM Provider Failed
```
[inf] Validating critical components...
[crit] CRITICAL: LLM provider validation failed: No LLM providers available. Errors: ...
[crit] Startup validation failed. Critical components not ready: llm_provider
```
**Результат:** RuntimeError, додаток не стартує

### Redis Failed (якщо required)
```
[inf] Validating critical components...
[crit] CRITICAL: Redis validation failed (required but unavailable): Redis connection error: ...
[crit] Startup validation failed. Critical components not ready: redis
```
**Результат:** RuntimeError, додаток не стартує

---

## Health Check Endpoints

### `/health` - Liveness Probe
Повертає статус всіх компонентів (критичних та некритичних):
- HTTP 200: все працює
- HTTP 200 з `status: "degraded"`: некритичні компоненти недоступні

### `/health/ready` - Readiness Probe
Повертає статус тільки критичних компонентів:
- HTTP 200: всі критичні компоненти готові
- HTTP 503: хоча б один критичний компонент не готовий

**Очікуваний response при готовності:**
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

---

## Timing Expectations

- **Container start → Server ready:** ~3-5 секунд
- **LangGraph warmup:** ~10-20 секунд (перший deploy), ~1-2 секунди (наступні)
- **Critical components validation:** ~5-10 секунд
- **Total startup time:** ~15-35 секунд (перший deploy), ~5-10 секунд (наступні)

---

## Troubleshooting

### Проблема: Startup займає >60 секунд
**Можливі причини:**
- Повільне з'єднання з PostgreSQL
- Повільне з'єднання з OpenAI API
- Redis недоступний (якщо required)

**Рішення:**
- Перевірити network connectivity
- Перевірити database connection pool settings
- Перевірити Redis availability

### Проблема: Startup падає з RuntimeError
**Можливі причини:**
- Критичний компонент не готовий (checkpointer, LangGraph, LLM provider)
- Redis недоступний (якщо required)

**Рішення:**
- Перевірити логи для конкретного компонента
- Перевірити environment variables
- Перевірити database/Redis connectivity

### Проблема: `/health/ready` повертає 503
**Можливі причини:**
- Один з критичних компонентів не готовий
- Тимчасові проблеми з з'єднанням

**Рішення:**
- Перевірити `/health/ready` response для деталей
- Перевірити логи додатку
- Перевірити connectivity до критичних сервісів

---

## Monitoring

### Kubernetes Readiness Probe
```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Kubernetes Liveness Probe
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3
```

---

**Оновлено:** 24 грудня 2025, 22:30 UTC+2

