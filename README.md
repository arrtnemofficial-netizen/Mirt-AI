# Mirt-AI 🤖

AI-стиліст для бренду дитячого одягу **MIRT**.
Побудований на **LangGraph v2**, **Pydantic AI**, **Prompt Registry** та **Celery**.

[![Tests](https://img.shields.io/badge/tests-passed-brightgreen.svg)]()
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/architecture-v3.0-orange.svg)]()

## 🏗 Архітектура v3.0 (Golden Era)

Система перейшла на **File-Based Prompting** та **Strict Testing**.

### 🌟 Ключові зміни
1. **Prompt Registry** (`src/core/prompt_registry.py`): Всі промпти лежать в `data/prompts/` (Markdown/YAML) замість одного гігантського файлу.
2. **Golden Suite Testing** (`tests/data/golden_data.yaml`): Набір "золотих" сценаріїв, затверджених бізнесом (розмірна сітка 119см, оплата, кольори).
3. **Strict Validation**: Regex-перевірка кожного промпта на наявність критичних бізнес-правил (UnitTest).
4. **Celery Scalability**: Асинхронна обробка черг (LLM, CRM, Followups).

### Структура проекту

```
src/
├── core/                      # Kernel
│   ├── prompt_registry.py     # ⭐ SSOT: Завантажує промпти з md/yaml
│   ├── state_machine.py       # FSM: State logic
│   └── models.py              # Pydantic models
│
├── agents/                    # AI Brain
│   ├── graph_v2.py            # LangGraph оркестратор
│   └── pydantic/              # Pydantic AI агенти
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
| **LangGraph Agent** | Керує діалогом через 5 вузлів (Moderation -> Intent -> Plan -> Agent -> Validation). |
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
