# 📋 MIRT AI — Product Requirements Document (PRD)

> **Версія:** 1.0  
> **Дата:** 9 грудня 2025  
> **Статус:** Production Ready

---

## 🎯 ПРОДУКТ

**MIRT AI** — AI-консультант для магазину дитячого одягу MIRT.

### Ключові можливості
- 🖼️ **Vision:** Розпізнавання товарів по фото
- 💬 **Chat:** Консультація клієнтів українською
- 💳 **Payment:** Оформлення замовлень
- 📦 **CRM:** Інтеграція з Snitkix

---

## 👥 ЦІЛЬОВА АУДИТОРІЯ

| Персона | Потреба |
|---------|---------|
| **Мама** | Швидко знайти одяг для дитини за зростом/віком |
| **Подарунок** | Допомога з вибором без знання розмірів |
| **Постійний клієнт** | Запам'ятовування переваг та історії |

---

## 📊 КЛЮЧОВІ МЕТРИКИ

| Метрика | Ціль |
|---------|------|
| **Конверсія** | > 15% (від діалогу до замовлення) |
| **Час відповіді** | < 5 секунд |
| **Vision accuracy** | > 90% |
| **Fallback rate** | < 5% |
| **Ескалації** | < 3% |

---

## 🏗️ АРХІТЕКТУРА

```
Telegram/Instagram → FastAPI → LangGraph → PydanticAI → Supabase
                                   ↓
                              11 вузлів:
                    moderation, intent, vision, agent,
                    offer, payment, upsell, crm_error,
                    validation, escalation, memory
```

---

## ✅ РЕАЛІЗОВАНІ ФІЧІ (v1.0)

### Core
- [x] Multi-node LangGraph граф
- [x] PydanticAI агенти (Support, Vision, Payment)
- [x] PostgreSQL checkpointer
- [x] FSM з 10 станами

### Quality
- [x] **Multi-Role Deliberation** (STATE_4_OFFER)
- [x] Pre-validation цін з БД
- [x] Fallback на низькій впевненості

### Memory
- [x] **Titans-like 3-layer memory**
- [x] Persistent profiles
- [x] Fluid facts з time decay

### Integrations
- [x] Telegram webhook
- [x] ManyChat webhook
- [x] Snitkix CRM
- [x] Supabase

---

## 🗺️ ROADMAP

### Q1 2026
- [ ] RAG для великого каталогу
- [ ] Redis кешування
- [ ] A/B тестування офферів

### Q2 2026
- [ ] Voice messages
- [ ] Multi-language
- [ ] Analytics dashboard

---

## 📚 ДОКУМЕНТАЦІЯ

| Документ | Шлях |
|----------|------|
| **Центральний індекс** | [DOCUMENTATION.md](DOCUMENTATION.md) |
| **Гайд розробника** | [docs/DEV_SYSTEM_GUIDE.md](docs/DEV_SYSTEM_GUIDE.md) |
| **Статус реалізації** | [docs/STATUS_REPORT.md](docs/STATUS_REPORT.md) |
| **FSM переходи** | [docs/FSM_TRANSITION_TABLE.md](docs/FSM_TRANSITION_TABLE.md) |
| **Правила LLM** | [.rules/rulesllm.md](.rules/rulesllm.md) |

---

## 📞 КОНТАКТИ

**Team:** MIRT AI  
**Telegram:** @mirt_ua
