# 📉 Production Improvement Plan

> **Версія:** 5.0  
> **Status:** 🏗️ In Progress

---

## 🏆 Goals for Q1 2026

1. **Stability:** 99.9% uptime for Webhook API.
2. **Speed:** P95 response time < 3s.
3. **Quality:** Vision accuracy > 95%.

---

## 🛠️ Technical Debt

| Item | Impact | Effort | Owner |
|:-----|:-------|:-------|:------|
| **ManyChat Retry Logic** | Critical | Med | Backend |
| **Env Validation Audit** | High | Low | DevOps |
| **Unit Test Coverage** | Med | High | QA/Dev |
| **Docstrings Coverage** | Low | Med | Dev |

---

## 🚀 Enhancements Roadmap

### Phase 1: hardening (Now)
- [x] Push Mode for ManyChat
- [x] Checkpointer optimization
- [ ] **Circuit Breaker** for OpenAI API
- [ ] **Rate Limiter** per user (Redis)

### Phase 2: Intelligence (Next)
- [ ] **RAG System** for product catalog scaling (1000+ items)
- [ ] **Voice Processing** (Whisper integration)

### Phase 3: Scale (Future)
- [ ] **Kubernetes** migration (optional)
- [ ] **Geo-replication** for DB

---

## 📊 Success Metrics

- **Zero** `manychat_time_budget_exceeded` errors per week.
- **< 1%** `checkpointer_timeout` errors.
- **100%** traceability of orders in CRM.

---

> **Оновлено:** 20 грудня 2025, 13:56 UTC+2
