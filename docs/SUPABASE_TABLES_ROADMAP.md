# 🗄️ Supabase Tables Roadmap

> **Версія:** 5.0  
> **Статус:** ✅ Active schema

---

## 📊 Schema Overview

```mermaid
erDiagram
    agent_sessions ||--o{ messages : contains
    agent_sessions ||--o{ llm_traces : logs
    users ||--o{ agent_sessions : owns
    users ||--o{ mirt_memories : has
    
    agent_sessions {
        uuid id PK
        uuid user_id FK
        jsonb metadata
        timestamp created_at
        text status
    }

    messages {
        uuid id PK
        uuid session_id FK
        text role
        text content
        jsonb tool_calls
    }

    mirt_memories {
        uuid id PK
        uuid user_id FK
        vector embedding
        text content
        text memory_type
        float decay_factor
    }
```

---

## 📋 Core Tables

### 1. `agent_sessions`
Зберігає стан сесії LangGraph.

| Column | Type | Description |
|:-------|:-----|:------------|
| `session_id` | `text` | Telegram Chat ID / MC User ID |
| `checkpoint` | `bytea` | Serialized graph state |
| `metadata` | `jsonb` | Channel info, user profile |

### 2. `mirt_memories` (Vector Store)
Зберігає довгострокову пам'ять (Titans implementation).

| Column | Type | Description |
|:-------|:-----|:------------|
| `embedding` | `vector(1536)` | OpenAI embedding |
| `content` | `text` | Fact text |
| `importance` | `float` | 0.0 - 1.0 urgency |
| `last_accessed`| `timestamp` | For decay calculation |

---

## 🛠️ Planned Improvements (Roadmap)

### Q1 2026: Optimization

- [ ] **Partitioning:** Partition `messages` by month.
- [ ] **Archiving:** Move sessions > 3 months to cold storage (S3).
- [ ] **Indexing:** Add GIN index on `messages.metadata`.

### Q2 2026: Security

- [ ] **RLS Policies:** Strict Row Level Security per user.
- [ ] **Encryption:** Encrypt PII (phone, address) at rest.

---

> **Оновлено:** 20 грудня 2025, 13:54 UTC+2
