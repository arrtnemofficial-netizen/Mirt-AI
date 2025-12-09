# 📚 MIRT AI — ЦЕНТРАЛЬНИЙ ІНДЕКС ДОКУМЕНТАЦІЇ

> **Останнє оновлення:** 9 грудня 2025  
> **Версія архітектури:** 4.0 (Agentic System)  
> **Статус:** ✅ Production Ready (924 тести)

---

## 🎯 ШВИДКА НАВІГАЦІЯ

### ДЛЯ НОВИХ РОЗРОБНИКІВ
```
START HERE → README.md → docs/DEV_SYSTEM_GUIDE.md → docs/CONTRIBUTING.md
```

### ДЛЯ PROMPT ENGINEERS
```
data/prompts/ → docs/PROMPT_ENGINEERING.md → client_script/
```

### ДЛЯ DEVOPS / DEPLOYMENT
```
docs/DEPLOYMENT.md → docs/CELERY.md → docker-compose.yml
```

### ДЛЯ DEBUGGING / TESTING
```
docs/TESTING.md → docs/FSM_TRANSITION_TABLE.md → tests/
```

---

## 📁 СТРУКТУРА ДОКУМЕНТАЦІЇ

```
Mirt-AI/
│
├── 📖 РІВЕНЬ 0: КОРІНЬ (тільки головні файли) ────────────────
│   ├── README.md                    # 🌟 Головний огляд проекту
│   ├── DOCUMENTATION.md             # 📚 ЦЕЙ ФАЙЛ - центральний індекс
│   └── PRD.md                       # 📋 Product Requirements Document
│
├── 📜 РІВЕНЬ 1: ПРАВИЛА (.rules/) ────────────────────────────
│   └── rulesllm.md                  # ⚖️ ЗАЛІЗОБЕТОННІ правила для AI/LLM
│
├── 📚 РІВЕНЬ 2: ТЕХНІЧНА ДОКУМЕНТАЦІЯ (docs/) ────────────────
│   ├── README.md                    # Індекс папки docs
│   ├── DEV_SYSTEM_GUIDE.md          # 👨‍💻 Повний гайд розробника
│   ├── STATUS_REPORT.md             # 📊 Поточний статус реалізації
│   ├── AGENTS_ARCHITECTURE.md       # 🤖 Архітектура агентів
│   ├── FSM_TRANSITION_TABLE.md      # 🔀 Frozen spec: стани та переходи
│   ├── TESTING.md                   # 🧪 Стратегія тестування (Golden Suite)
│   ├── PROMPT_ENGINEERING.md        # ✏️ Гайд по промптах
│   ├── DEPLOYMENT.md                # 🚀 Інструкції деплою
│   ├── CELERY.md                    # ⚙️ Background tasks
│   ├── CONTRIBUTING.md              # 🤝 Правила контрибʼюції
│   │
│   ├── [LEGACY] ARCHITECTURE.md     # Історія v3.0
│   ├── [LEGACY] IMPLEMENTATION_STATUS.md  # Snapshot 2025-12-07
│   └── [ROADMAP] PRODUCTION_IMPROVEMENT_PLAN.md  # Плани розвитку
│
├── 🧠 РІВЕНЬ 3: AI ПРОМПТИ (data/prompts/) ───────────────────
│   ├── system/main.md               # Головний системний промпт
│   ├── vision/vision_main.md        # Vision Agent промпт
│   └── states/                      # FSM State-specific промпти
│       ├── STATE_0_INIT.md
│       ├── STATE_1_DISCOVERY.md
│       ├── STATE_2_VISION.md
│       ├── STATE_3_SIZE_COLOR.md
│       ├── STATE_4_OFFER.md         # Multi-Role Deliberation
│       ├── STATE_5_PAYMENT_DELIVERY.md
│       ├── STATE_6_UPSELL.md
│       ├── STATE_7_END.md
│       ├── STATE_8_COMPLAINT.md
│       └── STATE_9_OOD.md
│
├── 👁️ РІВЕНЬ 4: VISION СИСТЕМА (data/vision/) ────────────────
│   ├── README.md                    # Гайд Vision системи
│   ├── products_master.yaml         # 🔑 SSOT: Всі товари
│   ├── vision_main.md               # Vision промпт
│   └── generated/                   # Автогенеровані артефакти
│
├── 📝 РІВЕНЬ 5: КЛІЄНТСЬКІ ПРАВИЛА (client_script/) ──────────
│   ├── README.md                    # Огляд клієнтських правил
│   ├── MIRT_FULL_RULES.yaml         # Повні правила діалогу
│   └── CATALOG_MODELS.yaml          # Каталог моделей
│
└── 🔧 РІВЕНЬ 6: СКРИПТИ (scripts/) ───────────────────────────
    └── README_TELEGRAM_BOT.md       # Запуск Telegram бота
```

---

## 📋 МАТРИЦЯ ДОКУМЕНТІВ

### ПО ПРИЗНАЧЕННЮ

| Документ | Аудиторія | Призначення |
|----------|-----------|-------------|
| `README.md` | Всі | Перший погляд на проект |
| `PRD.md` | PM / Stakeholders | Product Requirements |
| `docs/DEV_SYSTEM_GUIDE.md` | Розробники | Повний технічний гайд |
| `docs/STATUS_REPORT.md` | Team Lead / PM | Поточний стан фіч |
| `docs/AGENTS_ARCHITECTURE.md` | AI Engineers | Архітектура агентів |
| `.rules/rulesllm.md` | AI Agents | Правила для LLM |
| `docs/FSM_TRANSITION_TABLE.md` | Всі розробники | Frozen spec роутингу |
| `docs/TESTING.md` | QA / Dev | Стратегія тестування |
| `docs/PROMPT_ENGINEERING.md` | Prompt Engineers | Робота з промптами |
| `docs/DEPLOYMENT.md` | DevOps | Деплой інструкції |
| `docs/CELERY.md` | Backend Dev | Background tasks |
| `docs/CONTRIBUTING.md` | Contributors | Правила контрибʼюції |
| `data/vision/README.md` | Vision Engineers | Vision система |
| `client_script/README.md` | Business / QA | Клієнтські правила |

### ПО СТАТУСУ

| Статус | Документи |
|--------|-----------|
| ✅ **АКТУАЛЬНІ** | `README.md`, `PRD.md`, `docs/DEV_SYSTEM_GUIDE.md`, `docs/STATUS_REPORT.md`, `docs/AGENTS_ARCHITECTURE.md`, `.rules/rulesllm.md`, `docs/FSM_TRANSITION_TABLE.md`, `docs/TESTING.md`, `docs/PROMPT_ENGINEERING.md`, `docs/DEPLOYMENT.md`, `docs/CELERY.md`, `docs/CONTRIBUTING.md` |
| 📜 **LEGACY** | `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_STATUS.md` |
| 🗺️ **ROADMAP** | `docs/PRODUCTION_IMPROVEMENT_PLAN.md` |

---

## 🔗 CROSS-REFERENCES

### Архітектура
- **Головний опис:** `docs/DEV_SYSTEM_GUIDE.md` (розділ 3-4)
- **Агенти детально:** `docs/AGENTS_ARCHITECTURE.md`
- **FSM переходи:** `docs/FSM_TRANSITION_TABLE.md`
- **Правила LLM:** `.rules/rulesllm.md`

### Multi-Role Deliberation (STATE_4_OFFER)
- **Статус реалізації:** `docs/STATUS_REPORT.md`
- **Модель:** `src/agents/pydantic/models.py` → `OfferDeliberation`
- **Промпт:** `data/prompts/states/STATE_4_OFFER.md`
- **Правила:** `.rules/rulesllm.md` (розділ 4.3)

### Memory System (Titans-like)
- **Архітектура:** `docs/AGENTS_ARCHITECTURE.md` (розділ 3.2)
- **Deps:** `src/agents/pydantic/deps.py` → `create_deps_with_memory`
- **Правила:** `.rules/rulesllm.md` (розділ 4.6)

### Vision
- **Гайд:** `data/vision/README.md`
- **Товари:** `data/vision/products_master.yaml`
- **Промпт:** `data/prompts/vision/vision_main.md`
- **Тести:** `tests/test_vision_health.py`, `tests/test_product_matcher.py`

### Промпти
- **Гайд:** `docs/PROMPT_ENGINEERING.md`
- **Системний:** `data/prompts/system/main.md`
- **По станах:** `data/prompts/states/STATE_*.md`
- **Клієнтські правила:** `client_script/MIRT_FULL_RULES.yaml`

---

## ⚡ QUICK COMMANDS

```bash
# Запуск тестів
pytest tests/ -v

# Запуск сервера
uvicorn src.server.main:app --reload --port 8000

# Перегенерувати Vision артефакти
python scripts/generate_vision_artifacts.py

# Форматування коду
ruff format src/
ruff check src/ --fix

# Docker
docker-compose up -d
```

---

## 📌 SSOT (Single Source of Truth)

| Що | Де | НЕ шукати тут |
|----|-----|---------------|
| **Архітектура** | `docs/DEV_SYSTEM_GUIDE.md` | `docs/ARCHITECTURE.md` (legacy) |
| **Стан фіч** | `docs/STATUS_REPORT.md` | `docs/IMPLEMENTATION_STATUS.md` (legacy) |
| **FSM переходи** | `docs/FSM_TRANSITION_TABLE.md` | Код (код слідує за доком) |
| **OUTPUT_CONTRACT** | `.rules/rulesllm.md` + `src/agents/pydantic/models.py` | - |
| **Товари Vision** | `data/vision/products_master.yaml` | `generated/*.json` (автогенеровані) |
| **Клієнтські правила** | `client_script/MIRT_FULL_RULES.yaml` | - |

---

> **🎯 ГОЛОВНЕ ПРАВИЛО:**
> 
> Якщо документ не в цьому індексі — він або застарілий, або не існує.
> Якщо ти створюєш новий документ — додай його сюди.
