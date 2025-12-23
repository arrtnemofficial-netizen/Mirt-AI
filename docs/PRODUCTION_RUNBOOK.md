# Production Runbook

> **Цей документ визначає SLO, метрики та процедури для production deployment.**

## Service Level Objectives (SLO)

### Latency Targets

| Метрика | p95 | p99 | Alert Threshold |
|---------|-----|-----|-----------------|
| `end_to_end_latency_ms` | < 10,000 ms (10s) | < 18,000 ms (18s) | p95 > 12s або p99 > 20s |
| `checkpointer_latency_ms` | < 1,000 ms (1s) | < 2,000 ms (2s) | p95 > 1.5s або p99 > 3s |
| `llm_latency_ms` | < 5,000 ms (5s) | < 10,000 ms (10s) | p95 > 7s або p99 > 12s |
| Vision processing | < 35,000 ms (35s) | < 60,000 ms (60s) | p95 > 40s або p99 > 70s |

### Error Rate Targets

| Метрика | Target | Alert Threshold |
|---------|--------|-----------------|
| `validation_errors` | < 1% | > 2% |
| `moderation_blocks` | < 0.5% | > 1% |
| `checkpointer_errors` | < 0.1% | > 0.5% |
| `llm_errors` | < 0.5% | > 1% |

### Availability

- **Target**: 99.5% uptime (monthly)
- **Alert**: < 99% за останні 24 години

## Key Metrics

### Core Metrics (Tracked via `src/services/observability.py`)

1. **`end_to_end_latency_ms`**: Повний час обробки повідомлення від отримання до відправки відповіді
   - Tags: `state`, `intent`
   - Tracked in: `src/services/conversation.py::process_message`

2. **`checkpointer_latency_ms`**: Час операцій з checkpointer (aget_tuple, aput, aput_writes)
   - Tags: `operation` (aget_tuple, aput, aput_writes)
   - Tracked in: `src/agents/langgraph/checkpointer.py::_log_if_slow`

3. **`llm_latency_ms`**: Час виклику LLM (run_support)
   - Tags: `state`, `intent`
   - Tracked in: `src/agents/langgraph/nodes/agent.py::agent_node`

### Secondary Metrics

- `agent_step_latency_ms`: Latency окремого кроку агента
- `tool_latency_ms`: Latency викликів tool (catalog search, etc.)
- `validation_errors`: Кількість помилок валідації
- `moderation_blocks`: Кількість заблокованих повідомлень

## Release Strategy: Canary Deployment

### Phase 1: Canary (5-10% traffic)

1. **Deploy canary version** з новим feature flag або версією
2. **Monitor metrics** протягом 15-30 хвилин:
   - Перевірити що p95/p99 latency не перевищують thresholds
   - Перевірити що error rate не зріс
   - Перевірити що checkpointer latency стабільна
3. **Rollback criteria**:
   - p95 latency > 12s (end_to_end) або > 1.5s (checkpointer)
   - Error rate > 2% (validation) або > 1% (llm)
   - Будь-які критичні помилки (checkpointer failures, state loss)

### Phase 2: Full Rollout

1. Якщо canary успішна → deploy до всіх instances
2. Продовжити моніторинг протягом 1-2 годин
3. Rollback якщо виникають проблеми

### Rollback Procedure

```bash
# 1. Revert to previous version
git revert <commit-hash>
# or
git checkout <previous-tag>

# 2. Redeploy
# (залежить від deployment platform: Railway, Docker, etc.)

# 3. Verify metrics return to baseline
# Перевірити що latency та error rate повернулися до нормальних значень
```

## Monitoring & Alerts

### Recommended Alert Rules

```yaml
# Example Prometheus/AlertManager rules (if using Prometheus)
groups:
  - name: mirt_ai_slo
    rules:
      - alert: HighEndToEndLatency
        expr: histogram_quantile(0.95, rate(end_to_end_latency_ms_bucket[5m])) > 12000
        for: 5m
        annotations:
          summary: "p95 end-to-end latency > 12s"

      - alert: HighCheckpointerLatency
        expr: histogram_quantile(0.95, rate(checkpointer_latency_ms_bucket[5m])) > 1500
        for: 5m
        annotations:
          summary: "p95 checkpointer latency > 1.5s"

      - alert: HighLLMLatency
        expr: histogram_quantile(0.95, rate(llm_latency_ms_bucket[5m])) > 7000
        for: 5m
        annotations:
          summary: "p95 LLM latency > 7s"

      - alert: HighErrorRate
        expr: rate(validation_errors_total[5m]) / rate(agent_step_total[5m]) > 0.02
        for: 5m
        annotations:
          summary: "Validation error rate > 2%"
```

### Log Analysis

Ключові логи для моніторингу:

- `agent_step`: Структуровані логи кожного кроку агента (latency, state, intent)
- `[CHECKPOINTER]`: Логи операцій checkpointer (latency, size_bytes, messages)
- `tool_execution`: Логи викликів tools (catalog search, etc.)

Приклад фільтрації:

```bash
# Знайти повільні операції checkpointer (> 1s)
grep "\[CHECKPOINTER\]" logs.txt | grep "took [1-9]\.[0-9]"

# Знайти високі end-to-end latency (> 10s)
grep "end_to_end_latency_ms" logs.txt | awk '$2 > 10000'

# Знайти помилки валідації
grep "validation_errors" logs.txt | grep -v "validation_errors=0"
```

## Troubleshooting

### High Checkpointer Latency

**Симптоми**: `checkpointer_latency_ms` p95 > 1.5s

**Можливі причини**:
1. DB connection pool exhaustion
2. Slow Postgres queries
3. Network latency до Supabase

**Дії**:
1. Перевірити `CHECKPOINTER_POOL_MAX_SIZE` (зараз 2, можна збільшити до 5-8)
2. Перевірити DB connections: `SELECT count(*) FROM pg_stat_activity;`
3. Перевірити network latency до Supabase

### High LLM Latency

**Симптоми**: `llm_latency_ms` p95 > 7s

**Можливі причини**:
1. OpenAI API slowdown
2. Великий prompt (багато повідомлень в історії)
3. Model overload

**Дії**:
1. Перевірити OpenAI status page
2. Зменшити `LLM_MAX_HISTORY_MESSAGES` (зараз 20)
3. Розглянути backpressure policy (interim bubbles)

### High End-to-End Latency

**Симптоми**: `end_to_end_latency_ms` p95 > 12s

**Можливі причини**:
1. Комбінація checkpointer + LLM latency
2. Blocking operations в event loop
3. ManyChat API delays

**Дії**:
1. Проаналізувати breakdown: checkpointer + LLM latency
2. Перевірити що немає blocking sync calls
3. Розглянути async optimizations

## Pre-Deployment Checklist

- [ ] Всі тести пройшли (`pytest`)
- [ ] Smoke tests пройшли (`tests/smoke/`)
- [ ] Метрики додані та працюють
- [ ] SLO визначені та зафіксовані в runbook
- [ ] Canary deployment plan готовий
- [ ] Rollback procedure протестована
- [ ] Monitoring/alerting налаштований

## Post-Deployment Checklist

- [ ] Перевірити метрики протягом 15-30 хвилин
- [ ] Перевірити що latency в межах SLO
- [ ] Перевірити що error rate в межах targets
- [ ] Перевірити логи на несподівані помилки
- [ ] Перевірити що checkpointer працює стабільно

---

**Last Updated**: 2025-01-XX  
**Version**: 1.0

