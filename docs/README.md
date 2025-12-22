# 📚 MIRT AI Documentation

Центральна документація проекту MIRT AI.

## 📁 Структура документації

### 🎯 Quality & Assessment (`quality/`)
Оцінка якості реалізації та правила безпеки:
- **[PYDANTICAI_LANGGRAPH_QUALITY_ASSESSMENT.md](quality/PYDANTICAI_LANGGRAPH_QUALITY_ASSESSMENT.md)** - Оцінка якості реалізації PydanticAI та LangGraph (100/100)
- **[SAFEGUARDS_RULES.md](quality/SAFEGUARDS_RULES.md)** - ⚠️ **КРИТИЧНО:** Залізобетонні правила безпеки для 7 кастомних оптимізацій (ZB_ENGINE_V6 стиль)
- **[SAFEGUARDS_TESTS_SUMMARY.md](quality/SAFEGUARDS_TESTS_SUMMARY.md)** - ✅ Підсумок тестів запобіжників (38/38 тестів проходять)
- **[PYDANTICAI_LANGGRAPH_USAGE.md](quality/PYDANTICAI_LANGGRAPH_USAGE.md)** - Статистика використання PydanticAI та LangGraph

### 📦 Dependencies (`dependencies/`)
Аналіз залежностей та конфліктів:
- **[DEPENDENCY_ANALYSIS.md](dependencies/DEPENDENCY_ANALYSIS.md)** - Аналіз залежностей на конфлікти та актуальність
- **[DEPENDENCY_FIX_SUMMARY.md](dependencies/DEPENDENCY_FIX_SUMMARY.md)** - Підсумок виправлень конфліктів залежностей

### 🔒 Security (`security/`)
Безпека та аудит:
- **[SECURITY_AUDIT_REPORT.md](security/SECURITY_AUDIT_REPORT.md)** - Звіт аудиту безпеки
- **[SECURITY.md](security/SECURITY.md)** - Політика безпеки

### 🧪 Testing (`testing/`)
Тестування та звіти:
- **[TESTING.md](testing/TESTING.md)** - Стратегія тестування
- **[TEST_STRATEGY_AUDIT.md](testing/TEST_STRATEGY_AUDIT.md)** - Аудит стратегії тестування
- **[test_failures_report.md](testing/test_failures_report.md)** - Звіт про помилки тестів
- **Тести запобіжників:** `tests/unit/safeguards/` - 38 тестів для всіх запобіжників

### 🏗️ Architecture (`architecture/`)
Архітектура та дизайн:
- **[ARCHITECTURE.md](architecture/ARCHITECTURE.md)** - Загальна архітектура системи
- **[AGENTS_ARCHITECTURE.md](architecture/AGENTS_ARCHITECTURE.md)** - Архітектура агентів
- **[architecture_rules.md](architecture/architecture_rules.md)** - Правила архітектури
- **[FSM_TRANSITION_TABLE.md](architecture/FSM_TRANSITION_TABLE.md)** - Таблиця переходів FSM
- **[architecture_guide_ua.md](architecture/architecture_guide_ua.md)** - Гайд по архітектурі (UA)
- **[analysis_old_conversation_py.md](architecture/analysis_old_conversation_py.md)** - Аналіз старої реалізації

### 🚀 Deployment (`deployment/`)
Деплой та інфраструктура:
- **[DEPLOYMENT.md](deployment/DEPLOYMENT.md)** - Інструкції по деплою
- **[DEPLOYMENT_VPS.md](deployment/DEPLOYMENT_VPS.md)** - Деплой на VPS
- **[DEV_SYSTEM_GUIDE.md](deployment/DEV_SYSTEM_GUIDE.md)** - Гайд по розробницькій системі

### 🔌 Integrations (`integrations/`)
Інтеграції з зовнішніми сервісами:
- **[SITNIKS_INTEGRATION.md](integrations/SITNIKS_INTEGRATION.md)** - Інтеграція з Sitniks CRM
- **[MANYCHAT_SETUP.md](integrations/MANYCHAT_SETUP.md)** - Налаштування ManyChat
- **[MANYCHAT_PUSH_MODE.md](integrations/MANYCHAT_PUSH_MODE.md)** - Push режим ManyChat

### 📊 Observability (`observability/`)
Моніторинг та спостереження:
- **[OBSERVABILITY_RUNBOOK.md](observability/OBSERVABILITY_RUNBOOK.md)** - Runbook по observability

### ⚙️ Operations (`operations/`)
Операційні документи:
- **[CELERY.md](operations/CELERY.md)** - Документація по Celery workers
- **[STATUS_REPORT.md](operations/STATUS_REPORT.md)** - Статус репорт
- **[IMPLEMENTATION_STATUS.md](operations/IMPLEMENTATION_STATUS.md)** - Статус імплементації

### 📝 Development (`development/`)
Розробка та контрибуція:
- **[CONTRIBUTING.md](development/CONTRIBUTING.md)** - Гайд для контриб'юторів
- **[PROMPT_ENGINEERING.md](development/PROMPT_ENGINEERING.md)** - Prompt engineering гайд
- **[PRODUCTION_IMPROVEMENT_PLAN.md](development/PRODUCTION_IMPROVEMENT_PLAN.md)** - План покращень для production

### 🗄️ Database (`database/`)
База даних та схеми:
- **[SUPABASE_TABLES_ROADMAP.md](database/SUPABASE_TABLES_ROADMAP.md)** - Roadmap таблиць Supabase

### 📋 ADRs (`adr/`)
Architecture Decision Records:
- **[ADR_vision_ledger.md](adr/ADR_vision_ledger.md)** - ADR по vision ledger
- **[vision_identity.md](adr/vision_identity.md)** - Vision identity

---

## 🔍 Швидкий пошук

### Якщо потрібно знайти:

- **Правила безпеки та запобіжники** → `quality/SAFEGUARDS_RULES.md` ⚠️ **КРИТИЧНО**
- **Тести запобіжників** → `tests/unit/safeguards/` (38 тестів, всі проходять ✅)
- **Підсумок тестів** → `quality/SAFEGUARDS_TESTS_SUMMARY.md`
- **Оцінка якості реалізації** → `quality/PYDANTICAI_LANGGRAPH_QUALITY_ASSESSMENT.md`
- **Конфлікти залежностей** → `dependencies/DEPENDENCY_ANALYSIS.md`
- **Архітектура системи** → `architecture/ARCHITECTURE.md`
- **Інтеграція з CRM** → `integrations/SITNIKS_INTEGRATION.md`
- **Деплой** → `deployment/DEPLOYMENT.md`
- **Тестування** → `testing/TESTING.md`
- **Безпека** → `security/SECURITY.md`

---

## 📅 Останні оновлення

- **22.12.2025** - Створено структуру документації, додано правила безпеки (SAFEGUARDS_RULES.md)
- **22.12.2025** - Оновлено оцінку якості до 100/100 з запобіжниками
- **22.12.2025** - Вирішено конфлікти залежностей

---

## 🔗 Посилання

- [Головний README](../README.md)
- [Архітектура](architecture/ARCHITECTURE.md)
- [Правила безпеки](quality/SAFEGUARDS_RULES.md)
