# ENV Variables Migration: Supabase → PostgreSQL

## 📋 Що змінилося


```bash
# ⚠️ ВИДАЛИТИ - Supabase більше НЕ використовується!
```

**Чому видалити?** 
- Система тепер підключається **напряму до PostgreSQL** через `DATABASE_URL`
- Supabase API більше не використовується
- Всі stores (SessionStore, MessageStore) працюють тільки з PostgreSQL
- Немає fallback на Supabase - тільки PostgreSQL або in-memory (для тестів)

### ✅ Залишити БЕЗ ЗМІН (працюють як раніше)

```bash
# PostgreSQL connection - ОСНОВНА змінна

# LangGraph checkpointer (вже налаштований на postgres)
LANGGRAPH_CHECKPOINTER="postgres"

# Всі інші змінні залишаються без змін:
PUBLIC_BASE_URL="https://mirt-ai-production.up.railway.app"
OPENAI_API_KEY="..."
AI_MODEL="gpt-5.1"
# ... і так далі
```

### ➕ Додати (опціонально, для оптимізації)

```bash
# Опціональні налаштування пулу з'єднань PostgreSQL
POSTGRES_POOL_MIN_SIZE=1
POSTGRES_POOL_MAX_SIZE=10
POSTGRES_POOL_MAX_IDLE=30
```

**Чому?** Дозволяють налаштувати connection pool для кращої продуктивності.

## 🔄 Оновлений список ENV (повний)

```bash
# ============================================================================
# Application
# ============================================================================
PUBLIC_BASE_URL="https://mirt-ai-production.up.railway.app"
DEFAULT_SESSION_ID=""

# ============================================================================
# OpenAI / LLM
# ============================================================================
OPENAI_API_KEY="sk-proj-..."
AI_MODEL="gpt-5.1"
LLM_PROVIDER="openai"
LLM_MODEL_GPT="gpt-5.1"
LLM_MODEL_VISION="gpt-5.1"
LLM_REASONING_EFFORT="medium"
LLM_TEMPERATURE="0.3"
LLM_MAX_TOKENS="2048"
LLM_MAX_HISTORY_MESSAGES="20"
PROMPT_TEMPLATE="default"

# ============================================================================
# Telegram
# ============================================================================
MANAGER_BOT_TOKEN="8508650467:AAFl4_8PhGXnnY2C6494C6nkYbfZq5gw6Oo"
MANAGER_CHAT_ID="5863750352"

# ============================================================================
# ManyChat
# ============================================================================
MANYCHAT_API_KEY="2926449:8ac8eaf553cb7dd2dfbfbe2b56dbd455"
MANYCHAT_VERIFY_TOKEN="kL2nM4oP6qR8sT0uV1wX3yZ5aB7cD9eF1gH3iJ5kL7mN9"
MANYCHAT_API_URL="https://api.manychat.com"
MANYCHAT_PAGE_ID=""
MANYCHAT_PUSH_MODE="true"
MANYCHAT_USE_CELERY="true"
MANYCHAT_IMAGE_PROXY_ENABLED="false"
MANYCHAT_DEBOUNCE_SECONDS="5.0"
MANYCHAT_FALLBACK_AFTER_SECONDS="10.0"
MANYCHAT_INTERIM_TEXT=""
MANYCHAT_INTERIM_TEXT_WITH_IMAGE=""
MANYCHAT_TEXT_TIME_BUDGET_SECONDS="22.0"
MANYCHAT_VISION_TIME_BUDGET_SECONDS="55.0"
MANYCHAT_SAFE_MODE_INSTAGRAM="true"
MANYCHAT_INSTAGRAM_DISABLE_ACTIONS="true"
MANYCHAT_INSTAGRAM_ALLOWED_FIELDS="ai_state,ai_intent"
MANYCHAT_INSTAGRAM_SPLIT_SEND="true"
MANYCHAT_INSTAGRAM_BUBBLE_DELAY_SECONDS="5.0"

# ============================================================================
# Media Proxy
# ============================================================================
MEDIA_PROXY_ENABLED="true"
MEDIA_PROXY_ALLOWED_HOSTS="cdn.sitniks.com"
MEDIA_PROXY_TOKEN=""

# ============================================================================
# PostgreSQL (ОСНОВНЕ ПІДКЛЮЧЕННЯ)
# ============================================================================
# ⭐ ОБОВ'ЯЗКОВА змінна - підключення до PostgreSQL

# Опціонально: альтернативна змінна (якщо DATABASE_URL порожня)
# POSTGRES_URL="postgresql://..."

# Опціонально: налаштування пулу з'єднань
POSTGRES_POOL_MIN_SIZE=1
POSTGRES_POOL_MAX_SIZE=10
POSTGRES_POOL_MAX_IDLE=30

# ============================================================================
# LangGraph Checkpointer (використовує DATABASE_URL)
# ============================================================================
LANGGRAPH_CHECKPOINTER="postgres"
CHECKPOINTER_WARMUP="true"
CHECKPOINTER_WARMUP_TIMEOUT_SECONDS="15"
CHECKPOINTER_POOL_MIN_SIZE="0"
CHECKPOINTER_POOL_MAX_SIZE="2"
CHECKPOINTER_POOL_TIMEOUT_SECONDS="5"
CHECKPOINTER_POOL_MAX_IDLE_SECONDS="30"
CHECKPOINTER_CONNECT_TIMEOUT_SECONDS="10"
CHECKPOINTER_STATEMENT_TIMEOUT_MS="5000"
CHECKPOINTER_LOCK_TIMEOUT_MS="1000"
CHECKPOINTER_SLOW_LOG_SECONDS="0.5"
STATE_MAX_MESSAGES="100"
CHECKPOINTER_MAX_MESSAGES="200"
CHECKPOINTER_MAX_MESSAGE_CHARS="4000"
CHECKPOINTER_DROP_BASE64="true"

# ============================================================================
# Business Logic
# ============================================================================
SUMMARY_RETENTION_DAYS="3"
FOLLOWUP_DELAYS_HOURS="24,72"
DISABLE_CODE_STATE_PROMPTS_FALLBACK="false"
USE_OFFER_DELIBERATION="true"
DELIBERATION_MIN_CONFIDENCE="0.6"
ENABLE_PAYMENT_HITL="false"
DEBOUNCER_DELAY_SECONDS="4"

# ============================================================================
# CRM Integration
# ============================================================================
SNITKIX_API_URL="https://crm.sitniks.com"
SNITKIX_API_KEY="1OnP2q1i6DZAWJNkfUcVqCCAiSpbRMjOiNVkB0I3Ifi"
ENABLE_CRM_INTEGRATION="true"
SITNIKS_AI_MANAGER_NAME="AI_Manager"

# ============================================================================
# Celery / Redis
# ============================================================================
REDIS_URL="redis://default:iZpziwNDqnRMBzeTLhMwzdywpXXRdMbq@redis.railway.internal:6379"
CELERY_ENABLED="true"
CELERY_RESULT_TIMEOUT="25"
CELERY_EAGER="false"
CELERY_CONCURRENCY="4"
CELERY_MAX_TASKS_PER_CHILD="100"

# ============================================================================
# Monitoring
# ============================================================================
SENTRY_DSN=""
SENTRY_ENVIRONMENT="development"
SENTRY_TRACES_SAMPLE_RATE="0.1"
DEBUG_TRACE_LOGS="false"
```

## 🔍 Детальне пояснення змін

### Чому видалили ВСЕ про Supabase?

**Раніше (Supabase):**
```
Application → Supabase Client → Supabase REST API → PostgreSQL
```

**Тепер (PostgreSQL напряму):**
```
Application → PostgreSQL Client → PostgreSQL (напряму)
```

**Переваги:**
- ✅ Швидше (немає API шар)
- ✅ Менше залежностей
- ✅ Прямий контроль над SQL
- ✅ Менше вартість (без Supabase subscription)
- ✅ Простіша архітектура

### Чому DATABASE_URL залишається?

`DATABASE_URL` - це **вже PostgreSQL connection string**, не Supabase!

Він використовується для:
- ✅ SessionStore (зберігання стану діалогів)
- ✅ MessageStore (зберігання повідомлень)
- ✅ WebhookDedupeStore (дедуплікація)
- ✅ Observability (логування трас)
- ✅ Workers (summarization, followups, llm_usage, crm)
- ✅ LangGraph checkpointer


## ✅ Чеклист міграції

- [ ] Перевірити що `DATABASE_URL` встановлена ✅
- [ ] (Опціонально) Додати `POSTGRES_POOL_*` змінні
- [ ] Перевірити підключення: `python scripts/test_postgres_stores.py`

## 🚨 Важливо!

**НЕ видаляйте `DATABASE_URL`!** Це основна змінна для підключення до PostgreSQL.

**Ваш поточний `DATABASE_URL` вже правильний:**
```bash
```

Це **вже PostgreSQL connection string** (навіть якщо хост від Supabase). Він працює напряму з PostgreSQL через pooler, без Supabase API.

**Підсумок:**
- ✅ `DATABASE_URL` - **ЗАЛИШИТИ** (це PostgreSQL)

