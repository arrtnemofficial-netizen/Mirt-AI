# 🤖 MIRT AI — Enterprise Implementation

<div align="center">

<img src="https://img.shields.io/badge/version-5.0-blue?style=flat-square" alt="Version">
<img src="https://img.shields.io/badge/architecture-LangGraph_v2-FF6B6B?style=flat-square" alt="Architecture">
<img src="https://img.shields.io/badge/integration-ManyChat_+_CRM-success?style=flat-square" alt="Integrations">

**Production-Ready AI Stylist for MIRT Clothing Brand**

[📖 Документація](docs/README.md) • [🏗️ Architecture](docs/architecture/ARCHITECTURE.md) • [⚙️ Deployment](docs/deployment/DEPLOYMENT.md) • [🔒 Правила безпеки](docs/quality/SAFEGUARDS_RULES.md)

</div>

---

## 🔥 Implementation Highlights

This repository contains the **v5.0 Enterprise Implementation** of MIRT AI.

- **Orchestrator:** `src.agents.langgraph.graph` (12 Nodes, Cyclic Graph).
- **Concurrency:** Celery Workers (`src.workers`) handling 5 distinct queues.
- **Integrations:**
  - **ManyChat:** Async Push Mode (`src.integrations.manychat`).
  - **CRM:** Snitkix Adapter (`src.integrations.crm`).
  - **Vision:** OpenAI GPT-4o (`src.agents.langgraph.nodes.vision`).

---

## 🛠️ Quick Start (Developer)

### 1. Requirements
- Python 3.11+
- Redis (Broker)
- PostgreSQL (Persistence)

### 2. Run Local
```bash
# Install
pip install -r requirements.txt

# Start Web Server (FastAPI)
uvicorn src.server.main:app --reload

# Start Worker (Terminal 2)
celery -A src.workers.celery_app worker -l info
```

---

## 📚 Documentation Index

| File | Description | Source Code Link |
|:-----|:------------|:-----------------|
| [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) | High-level system design | `src/core/` |
| [**AGENTS_ARCHITECTURE.md**](docs/AGENTS_ARCHITECTURE.md) | Node-by-node graph logic | `src/agents/langgraph/` |
| [**CELERY.md**](docs/CELERY.md) | Queue & Schedule config | `src/workers/celery_app.py` |
| [**MANYCHAT_SETUP.md**](docs/MANYCHAT_SETUP.md) | Pipeline configuration | `src/integrations/manychat/` |
| [**SITNIKS_INTEGRATION.md**](docs/SITNIKS_INTEGRATION.md) | CRM payloads & logic | `src/integrations/crm/` |
| [**DEPLOYMENT.md**](docs/DEPLOYMENT.md) | Production setup | `Dockerfile` |

---

## 🧪 Testing

We achieve reliability through the **Test Pyramid** (flat `tests/` layout):

- **Core:** `pytest tests` (No mocks in tests; no env required)
- **Live:** `pytest live_test` (Real services only; env required)
- **Golden:** `pytest tests -m golden` (Quality assurance)

---

## ManyChat

- `/webhooks/manychat`: Primary webhook (push mode + async service)

---

<div align="center">
Built with ❤️ by MIRT Team
</div>
