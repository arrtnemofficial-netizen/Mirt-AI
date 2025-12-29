# Mirt-AI 🤖

AI-стиліст для бренду дитячого одягу **MIRT**.
Побудований на **LangGraph**, **Pydantic AI**, **Prompt Registry** та **Celery**.

[![Tests](https://img.shields.io/badge/tests-39%2F39_passed-brightgreen.svg)]()
[![Readiness](https://img.shields.io/badge/production_ready-95%25-brightgreen.svg)]()
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## 🚀 Quick Links
- **[DEPLOY.md](DEPLOY.md)** - Інструкції запуску (Railway/Docker) 🆕
- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Повна документація
- **[PRD.md](PRD.md)** - Вимоги та Roadmap

## 🏗 Архітектура v4.0 (Agentic System)

Система перейшла на **File-Based Prompting** та **Strict Testing**.

### 🌟 Ключові зміни
1. **Prompt Registry** (`src/core/prompt_registry.py`): Всі промпти лежать в `data/prompts/` (Markdown/YAML) замість одного гігантського файлу.
2. **Golden Suite Testing** (`tests/data/golden_data.yaml`): Набір "золотих" сценаріїв, затверджених бізнесом (розмірна сітка 119см, оплата, кольори).
3. **Strict Validation**: Regex-перевірка кожного промпта на наявність критичних бізнес-правил (UnitTest).
4. **Celery Scalability**: Асинхронна обробка черг (LLM, CRM, Followups).
5. **Agentic LangGraph + PydanticAI**: багатовузловий граф (moderation, intent, vision, agent, offer, payment, upsell, validation, escalation, crm_error, memory) + строгі моделі OUTPUT_CONTRACT.

### Структура проекту

```
src/
├── core/                      # Kernel
│   ├── prompt_registry.py     # ⭐ SSOT: Завантажує промпти з md/yaml
│   ├── state_machine.py       # FSM: State logic
│   └── models.py              # Pydantic models
│
├── agents/                    # AI Brain
│   ├── pydantic/              # Pydantic AI агенти (Support/Vision/Payment)
│   └── langgraph/             # LangGraph оркестрація
│       ├── graph.py           # Production Graph Builder
│       ├── state.py           # ConversationState + reducers
│       ├── edges.py           # master_router + routing
│       └── nodes/             # Ноди: moderation, intent, vision, agent, offer, payment, upsell, crm_error, validation, escalation, memory
│
├── workers/                   # Background Tasks
│   └── tasks/messages.py      # AI processing
│
data/
├── prompts/                   # 🧠 Prompt Knowledge Base
│   ├── system/main.md         # Головний промпт (Role, Tone, Rules)
│   ├── states/STATE_*.md      # Промпти для кожного стану FSM
│   └── vision/                # Vision Rules
│
tests/                         # 🛡️ Production QA
├── data/golden_data.yaml      # "Truth" Source
├── unit/                      # Prompt & Logic tests
└── integration/               # Agent simulation
```

### Ключові компоненти

| Модуль | Призначення |
| :--- | :--- |
| **PromptRegistry** | Керує версійністю та завантаженням всіх промптів. |
| **LangGraph Graph** | Керує діалогом через багатовузловий граф (Moderation, Intent, Vision, Agent, Offer, Payment, Upsell, Validation, Escalation, CRM Error, Memory). |
| **Golden Suite** | Гарантує, що AI ніколи не порушить критичні правила (напр. "білий=молочний"). |

## 🚀 Testing Strategy "Golden Suite"

Ми використовуємо підхід **Truth-Driven Development**:

1. **Golden Data** (`tests/data/golden_data.yaml`): Бізнес пише правила тут.
2. **Unit Tests** (`tests/unit/`): Перевіряють, що промпти містять точні формулювання.
3. **Integration Tests** (`tests/integration/`): Емулюють повний цикл діалогу.

Запуск тестів:
```bash
pytest
```

## 📚 Документація

Повний індекс документації: **[DOCUMENTATION.md](DOCUMENTATION.md)**

| Документ | Опис |
|----------|------|
| [PRD.md](PRD.md) | Product Requirements Document |
| [docs/DEV_SYSTEM_GUIDE.md](docs/DEV_SYSTEM_GUIDE.md) | Повний гайд розробника |
| [docs/STATUS_REPORT.md](docs/STATUS_REPORT.md) | Поточний статус реалізації |
| [docs/AGENTS_ARCHITECTURE.md](docs/AGENTS_ARCHITECTURE.md) | Архітектура агентів |
| [.rules/rulesllm.md](.rules/rulesllm.md) | Правила для AI/LLM |

## 🛠 Технології

- **LLM**: GPT-4o / Gemini 1.5 Pro
- **Framework**: LangGraph v2 + Pydantic AI
- **Backend**: FastAPI + Celery + Redis
- **Data**: Supabase (PostgreSQL)

## 📦 Deployment (Railway)

Всі змінні середовища налаштовані через `railway.json`.
Для запуску локально:
```bash
docker-compose up -d
```
