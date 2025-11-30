# MIRT AI Architecture

## Overview

MIRT AI is an intelligent shopping assistant for children's clothing, built on a modern, type-safe stack. It combines **LangGraph** for orchestration and **PydanticAI** for strict structured outputs.

## Tech Stack

- **Orchestration**: LangGraph (StateGraph, checkpointer, nodes)
- **Agents**: PydanticAI (Type-safe LLM wrapper)
- **Runtime**: FastAPI (Webhooks, REST API)
- **Persistence**: PostgreSQL (via Supabase)
- **Background Tasks**: Celery + Redis
- **Observability**: Logfire + Sentry

---

## 🏗️ High-Level Architecture

```mermaid
graph TD
    User((User)) -->|Message| Telegram[Telegram/ManyChat]
    Telegram -->|Webhook| FastAPI[FastAPI Server]
    
    subgraph "AI Core (LangGraph)"
        FastAPI -->|Invoke| Graph[LangGraph Orchestrator]
        
        Graph -->|Check| Moderation[Moderation Node]
        Moderation -->|Allowed| Intent[Intent Node]
        Moderation -->|Blocked| Escalation[Escalation Node]
        
        Intent -->|Routing| Router{Router}
        
        Router -->|Support| Agent[Support Agent (PydanticAI)]
        Router -->|Payment| Payment[Payment Node]
        Router -->|Vision| Vision[Vision Agent (PydanticAI)]
        
        Agent -->|Tool Call| Tools[Catalog/CRM Tools]
        
        Payment -->|HITL| Human[Human Review]
    end
    
    subgraph "Data Layer"
        Graph -->|State| Postgres[(Supabase DB)]
        Agent -->|Catalog| JSON[Catalog.json]
        Tools -->|Orders| CRM[Snitkix CRM]
    end
```

---

## 🧩 Key Components

### 1. Agents Layer (`src/agents/pydantic/`)
Powered by **PydanticAI**. Ensures 100% schema compliance for LLM outputs.

- **Support Agent**: Main conversationalist. Handles sizing, product questions.
- **Vision Agent**: Analyzes photos (receipts, product issues).
- **Payment Agent**: Processes orders and payments.

### 2. Orchestration Layer (`src/agents/langgraph/`)
Powered by **LangGraph**. Manages conversation flow and state.

- **Graph**: Defines the DAG (Directed Acyclic Graph) of the conversation.
- **State**: `ConversationState` (TypedDict) holding messages and metadata.
- **Persistence**: `PostgresSaver` stores state in Supabase.

### 3. Service Layer (`src/services/`)
Business logic decoupled from the AI core.

- `message_store.py`: Logs raw messages.
- `client_data_parser.py`: Parses ManyChat payloads.
- `moderation.py`: Safety checks.
- `order_model.py`: CRM data contracts.

### 4. Worker Layer (`src/workers/`)
Background processing via Celery.

- `tasks/crm.py`: Async order creation.
- `tasks/messages.py`: Async message processing.
- `dispatcher.py`: Routes tasks (Sync vs Async support).

---

## 🔄 Data Flow

1. **Webhook**: Received by `src/server/main.py`.
2. **Persist**: User message saved to `message_store`.
3. **Invoke**: `get_active_graph().ainvoke()` called.
4. **Process**: 
   - Moderation check.
   - Intent classification.
   - Agent execution (LLM inference).
   - Tool execution (if needed).
5. **Response**: Structured `SupportResponse` returned.
6. **Render**: Converted to text/images for platform (Telegram/ManyChat).

---

## 🛡️ Type Safety

We use strict typing everywhere:
- **Pydantic Models**: Define all data contracts (`src/core/models.py`, `src/agents/pydantic/models.py`).
- **Mypy**: Enforced strict mode in CI.
- **Ruff**: Enforced linting rules.

## 🚀 Deployment

- **Platform**: Railway / Docker
- **Config**: Environment variables (see `.env.example`)
- **CI/CD**: GitHub Actions (Lint -> Test -> Deploy)
