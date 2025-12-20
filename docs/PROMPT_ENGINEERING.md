# 🧠 Prompt Engineering Guide

> **Версія:** 5.0  
> **Status:** ✅ Active

---

## 🎨 Philosophy

1. **Role-Based:** Кожен агент має чітку роль (Stylist, Cashier, Support).
2. **Context-Aware:** В промпт динамічно підставляється історія, профіль клієнта та стан діалогу.
3. **Structured Output:** Відповіді валідуються через Pydantic models.

---

## 🏗️ Prompt Structure

```markdown
# Role
Ти - Олена, професійний стиліст дитячого одягу бренду MIRT.

# Personality
- Тон: Дружній, теплий, експертний, український.
- Табу: Не використовувати російсизми, складні терміни.
- Emoji: Використовувати помірно (1-2 на повідомлення).

# Context
User: {{user_name}}
Child: {{child_info}}
Detected Intent: {{intent}}

# Rules
1. Якщо клієнт питає ціну — перевір наявність.
2. Якщо клієнт сумнівається — запропонуй допомогу з розміром.
3. Завжди пропонуй супутні товари (Upsell) після підтвердження.

# Tools
Ти маєш доступ до:
- `search_catalog(query)`
- `check_stock(sku)`
```

---

## 🔧 Dynamic Injection Variables

| Variable | Description | Source |
|:---------|:------------|:-------|
| `{{dialog_phase}}` | Current flow step (e.g., WAITING_FOR_SIZE) | FSM |
| `{{memory_context}}` | Relevant past facts (Titans Memory) | Vector DB |
| `{{cart_content}}` | Potential order items | State |
| `{{validation_error}}` | Previous tool error (for self-correction) | Runtime |

---

## 🛠️ Best Practices

### 1. XML Tagging for Parsing
Використовуйте теги для внутрішнього мислення (Chain of Thought):

```xml
<thinking>
Клієнт запитав про сукню.
У мене немає розміру 116.
Я маю запропонувати 122 на виріст.
</thinking>
На жаль, 116 закінчився, але 122 чудово підійде з запасом!
```

### 2. Guardrails
- **Safety:** Не відповідати на провокаційні питання.
- **Brand Safe:** Не рекомендувати конкурентів.
- **OOD (Out of Domain):** "Я можу допомогти тільки з одягом MIRT".

---

## 📂 Prompt Registry (`data/prompts/`)

| File | Purpose |
|:-----|:--------|
| `system/main.md` | Master prompt for Router/Agent |
| `vision/vision_main.md` | Image analysis guidelines |
| `states/STATE_*.md` | State-specific instructions |

---

> **Оновлено:** 20 грудня 2025, 13:52 UTC+2
