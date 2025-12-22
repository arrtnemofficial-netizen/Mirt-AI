# 🦅 Observability & Runbook (Implementation)

> **Version:** 5.0 (Implementation)  
> **Source:** `src/integrations/manychat/pipeline.py` & `celery_app.py`  
> **Updated:** 20 December 2025

---

## 🎯 Key Application Metrics

Based on the actual code implementation in `src/integrations` and `workers`.

### 1. ManyChat Pipeline (`src.integrations.manychat.pipeline`)
| Log Signal | Meaning | Source File | Action |
|:-----------|:--------|:------------|:-------|
| `manychat_time_budget_exceeded` | Process took > `time_budget` (usually 25s) | `pipeline.py:68` | Check LLM latency or Queue depth. |
| `manychat_debounce_aggregated` | Multiple inputs merged into one. | `pipeline.py:45` | Normal behavior. Check `delay` value. |
| `manychat_debounce_superseded` | Request dropped (merged into newer). | `pipeline.py:47` | Normal behavior. |

### 2. Celery Worker (`src.workers.celery_app`)
| Log Signal | Meaning | Action |
|:-----------|:--------|:-------|
| `Task permanent failure` | `PermanentError` raised (no retry). | Investigate logic bug. |
| `Task rate limited` | `RateLimitError` raised (will retry). | Check external API limits. |
| `Checkpointer warmup skipped` | DB connection pool issue at startup. | Check `DATABASE_URL_POOLER`. |

### 3. LangGraph (`src.agents.langgraph.graph`)
| Log Signal | Meaning | Action |
|:-----------|:--------|:-------|
| `Graph starting with missing prompts` | Missing files in `data/prompts/`. | **CRITICAL:** Fix deployment immediately. |
| `Graph invocation failed` | `invoke_with_retry` exhausted 3 attempts. | Check OpenAI API status. |

---

## 🚨 Incident Runbook

### Case 1: "Message not delivered" (ManyChat)

1. **Check `llm` Queue:**
   ```bash
   redis-cli LLEN llm
   ```
   If > 100, workers are stuck.

2. **Check Logs for `manychat_time_budget_exceeded`:**
   If frequent, average LLM latency > 25s.
   *Fix:* Increase concurrency or switch model (e.g. from 4o to 4o-mini).

3. **Check `webhooks` Queue:**
   This queue sends the final response. If stuck here, ManyChat API might be down (`5xx` errors).

### Case 2: "Internal Server Error" (500)

1. **Supabase Pooler:**
   Check `[CELERY] Checkpointer warmup skipped`. If present, PG Bouncer is rejecting connections.
   *Fix:* `CLIENT_ENCODING` setting or Pool Mode (Transaction vs Session).

2. **OpenAI Rate Limit:**
   Search logic for `RateLimitError`.
   *Fix:* Worker will auto-retry. If persistent, increase quota.

---

## 📊 Dashboard Panels (Grafana)

1. **Pipeline Latency:** `avg(duration_ms) by (node)`
   - Target: `agent_node` < 3s, `vision_node` < 5s.

2. **Debounce Rate:** `rate(manychat_debounce_superseded)`
   - High rate = user types multiple short messages (Good).

3. **Queue Depth:** `redis_queue_length`
   - ALERT if `llm` > 50.

---
