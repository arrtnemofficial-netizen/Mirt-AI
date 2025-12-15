"""
Memory Agent - Titans-like Fact Classification.
================================================
Агент для класифікації фактів з діалогу.

Аналізує повідомлення і вирішує:
- Які факти запамʼятати (NewFact)
- Які факти оновити (UpdateFact)  
- Що ігнорувати (ignore_messages)

КЛЮЧОВЕ: виставляє importance + surprise (як Titans Surprise Metric)
- importance: наскільки факт впливає на рекомендації (0-1)
- surprise: наскільки це нова інформація (0-1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.agents.pydantic.memory_models import (
    Fact,
    MemoryDecision,
    UserProfile,
)
from src.conf.config import settings


logger = logging.getLogger(__name__)


# =============================================================================
# DEPENDENCIES
# =============================================================================


@dataclass
class MemoryDeps:
    """Dependencies for MemoryAgent."""

    user_id: str
    session_id: str | None = None

    # Current profile (for context)
    profile: UserProfile | None = None

    # Existing facts (for duplicate/update detection)
    existing_facts: list[Fact] = field(default_factory=list)

    # Recent messages to analyze
    messages_to_analyze: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

MEMORY_SYSTEM_PROMPT = """
Ти — Memory Analyzer для AI-консультанта магазину дитячого одягу MIRT.

## ТВОЯ ЗАДАЧА
Проаналізувати повідомлення клієнта і витягти ФАКТИ для довготривалої памʼяті.

## ЩО ВВАЖАТИ ФАКТОМ
ЗАПАМЯТАТИ (importance >= 0.6):
- Зріст/вік дитини: "доньці 7 років, зріст 128 см" → importance=1.0, surprise=0.9
- Улюблені моделі: "минулого разу брали Лагуну, дуже сподобалась" → importance=0.8, surprise=0.7
- Місто доставки: "я з Харкова" → importance=0.9, surprise=0.8
- Алергії/обмеження: "на синтетику алергія" → importance=1.0, surprise=1.0
- Переваги кольорів: "рожевий не носить" → importance=0.8, surprise=0.6
- Стать дитини: "для хлопчика" → importance=0.9, surprise=0.8

ІГНОРУВАТИ (importance < 0.6):
- "Дякую", "Добре", "Ок" → ignore_messages=True
- "Скільки коштує?" (без контексту) → не факт
- "Красиво", "Мені подобається" → занадто загально

## МЕТРИКИ (як в Titans Memory)

### importance (0.0-1.0)
Наскільки факт впливає на ВСІ наступні рекомендації:
- 1.0 = критичний (зріст дитини, алергія, місто)
- 0.8 = важливий (улюблена модель, переваги кольорів)
- 0.5 = помірний (одноразова згадка)
- 0.3 = мінорний (можна ігнорувати)

### surprise (0.0-1.0)
Наскільки це НОВА інформація порівняно з тим, що ми вже знаємо:
- 1.0 = абсолютно нове (перша згадка про зріст)
- 0.8 = неочікувана зміна (новий зріст, переїхали)
- 0.5 = підтвердження відомого
- 0.2 = повністю очікувано

## ТИПИ ФАКТІВ (fact_type)
- preference: вподобання (колір, стиль, модель)
- constraint: обмеження (алергія, не носить синтетику)
- logistics: логістика (місто, НП, адреса)
- behavior: поведінка (часто повертає, завжди купує акційне)
- feedback: зворотній звʼязок (скарга, похвала)
- child_info: інфо про дитину (вік, зріст, стать)

## КАТЕГОРІЇ (category)
- child: інфо про дитину
- style: стиль і вподобання
- delivery: доставка
- payment: оплата
- product: конкретний товар
- complaint: скарги
- general: загальне

## ПРАВИЛА ОНОВЛЕННЯ (UpdateFact)
Використовуй UpdateFact коли КОНФЛІКТ з існуючим фактом:
- Новий зріст (дитина виросла)
- Нове місто (переїхали)
- Змінились вподобання

## TTL (час життя факту)
- ttl_days: null = вічний факт (зріст, алергія)
- ttl_days: 90 = сезонні переваги
- ttl_days: 30 = тимчасові факти

## OUTPUT FORMAT
Повертай MemoryDecision з:
- new_facts: список NewFact для нових фактів
- updates: список UpdateFact для оновлень
- profile_updates: dict з оновленнями для профілю
- ignore_messages: True якщо немає нової інформації
- reasoning: коротке пояснення рішення
"""


# =============================================================================
# DYNAMIC PROMPTS
# =============================================================================


async def _add_profile_context(ctx: RunContext[MemoryDeps]) -> str:
    """Додати поточний профіль для контексту."""
    profile = ctx.deps.profile
    if not profile:
        return "\n--- ПРОФІЛЬ КЛІЄНТА: Новий клієнт, немає даних ---"

    lines = ["\n--- ПОТОЧНИЙ ПРОФІЛЬ КЛІЄНТА ---"]

    # Child info
    child = profile.child_profile
    if child.height_cm or child.age:
        child_info = []
        if child.name:
            child_info.append(f"імʼя: {child.name}")
        if child.age:
            child_info.append(f"вік: {child.age}")
        if child.height_cm:
            child_info.append(f"зріст: {child.height_cm} см")
        if child.gender:
            child_info.append(f"стать: {child.gender}")
        lines.append(f"Дитина: {', '.join(child_info)}")

    # Style
    style = profile.style_preferences
    if style.favorite_models:
        lines.append(f"Улюблені моделі: {', '.join(style.favorite_models)}")
    if style.favorite_colors:
        lines.append(f"Улюблені кольори: {', '.join(style.favorite_colors)}")
    if style.avoided_colors:
        lines.append(f"Уникає кольорів: {', '.join(style.avoided_colors)}")

    # Logistics
    logistics = profile.logistics
    if logistics.city:
        lines.append(f"Місто: {logistics.city}")
    if logistics.favorite_branch:
        lines.append(f"НП: {logistics.favorite_branch}")

    # Commerce
    commerce = profile.commerce
    if commerce.total_orders > 0:
        lines.append(f"Замовлень: {commerce.total_orders}")

    if len(lines) == 1:
        lines.append("(немає даних)")

    return "\n".join(lines)


async def _add_existing_facts(ctx: RunContext[MemoryDeps]) -> str:
    """Додати існуючі факти для перевірки дублів."""
    facts = ctx.deps.existing_facts
    if not facts:
        return "\n--- ВІДОМІ ФАКТИ: Немає ---"

    lines = ["\n--- ВІДОМІ ФАКТИ (для перевірки дублів) ---"]
    for fact in facts[:15]:  # Max 15
        lines.append(f"- [{fact.id}] [{fact.category}] {fact.content} (importance={fact.importance:.1f})")

    return "\n".join(lines)


async def _add_messages_to_analyze(ctx: RunContext[MemoryDeps]) -> str:
    """Додати повідомлення для аналізу."""
    messages = ctx.deps.messages_to_analyze
    if not messages:
        return "\n--- ПОВІДОМЛЕННЯ: Немає ---"

    lines = ["\n--- ПОВІДОМЛЕННЯ ДЛЯ АНАЛІЗУ ---"]
    for msg in messages[-10:]:  # Last 10
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:300]
        lines.append(f"{role.upper()}: {content}")

    return "\n".join(lines)


# =============================================================================
# MODEL SETUP (Lazy initialization)
# =============================================================================

_memory_model: OpenAIChatModel | None = None
_memory_agent: Agent[MemoryDeps, MemoryDecision] | None = None


def _get_memory_model() -> OpenAIChatModel:
    """Get or create model for memory agent."""
    global _memory_model
    if _memory_model is None:
        # Use same model config as support_agent
        if settings.LLM_PROVIDER == "openai":
            api_key = settings.OPENAI_API_KEY.get_secret_value()
            base_url = "https://api.openai.com/v1"
            model_name = settings.LLM_MODEL_GPT
        else:
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = settings.LLM_MODEL_GROK if settings.LLM_PROVIDER == "openrouter" else settings.AI_MODEL

        if not api_key:
            api_key = settings.OPENROUTER_API_KEY.get_secret_value()
            base_url = settings.OPENROUTER_BASE_URL
            model_name = settings.AI_MODEL

        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        provider = OpenAIProvider(openai_client=client)
        _memory_model = OpenAIChatModel(model_name, provider=provider)

    return _memory_model


# =============================================================================
# AGENT FACTORY
# =============================================================================


def get_memory_agent() -> Agent[MemoryDeps, MemoryDecision]:
    """Get or create the memory agent (lazy initialization)."""
    global _memory_agent
    if _memory_agent is None:
        _memory_agent = Agent(  # type: ignore[call-overload]
            _get_memory_model(),
            deps_type=MemoryDeps,
            output_type=MemoryDecision,  # PydanticAI 1.23+
            system_prompt=MEMORY_SYSTEM_PROMPT,
            retries=1,  # Memory is not critical, don't retry much
        )

        # Register dynamic prompts
        _memory_agent.system_prompt(_add_profile_context)
        _memory_agent.system_prompt(_add_existing_facts)
        _memory_agent.system_prompt(_add_messages_to_analyze)

    return _memory_agent


# =============================================================================
# RUNNER FUNCTION
# =============================================================================


async def analyze_for_memory(
    messages: list[dict[str, Any]],
    user_id: str,
    session_id: str | None = None,
    profile: UserProfile | None = None,
    existing_facts: list[Fact] | None = None,
) -> MemoryDecision:
    """
    Проаналізувати повідомлення і витягти факти для памʼяті.
    
    Це те, що викликає memory_update_node.
    
    Args:
        messages: Повідомлення для аналізу
        user_id: ID користувача
        session_id: ID сесії
        profile: Поточний профіль (для контексту)
        existing_facts: Існуючі факти (для перевірки дублів)
        
    Returns:
        MemoryDecision з класифікованими фактами
    """
    import asyncio

    agent = get_memory_agent()

    deps = MemoryDeps(
        user_id=user_id,
        session_id=session_id,
        profile=profile,
        existing_facts=existing_facts or [],
        messages_to_analyze=messages,
    )

    # Build analysis request
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        logger.debug("No user messages to analyze")
        return MemoryDecision(ignore_messages=True, reasoning="No user messages")

    # Combine last user messages for analysis
    analysis_text = "\n".join(
        m.get("content", "")[:500] for m in user_messages[-5:]
    )

    try:
        result = await asyncio.wait_for(
            agent.run(
                f"Проаналізуй ці повідомлення клієнта:\n\n{analysis_text}",
                deps=deps,
            ),
            timeout=30,  # Memory analysis shouldn't take long
        )

        decision = result.output
        logger.info(
            "Memory analysis for user %s: new=%d, updates=%d, ignore=%s",
            user_id,
            len(decision.new_facts),
            len(decision.updates),
            decision.ignore_messages,
        )
        return decision

    except TimeoutError:
        logger.warning("Memory agent timeout for user %s", user_id)
        return MemoryDecision(
            ignore_messages=True,
            reasoning="Timeout during analysis"
        )

    except Exception as e:
        logger.error("Memory agent error for user %s: %s", user_id, e)
        return MemoryDecision(
            ignore_messages=True,
            reasoning=f"Error: {str(e)[:100]}"
        )


# =============================================================================
# QUICK FACTS EXTRACTION (without LLM)
# =============================================================================


def extract_quick_facts(message: str) -> list[dict[str, Any]]:
    """
    Швидкий regex-based витяг фактів (без LLM).
    
    Для випадків коли потрібно швидко витягти очевидні факти:
    - Зріст: "128 см", "зріст 128"
    - Вік: "7 років", "доньці 7"
    - Місто: "з Харкова", "в Києві"
    
    Returns:
        List of dicts with extracted facts (no importance/surprise - use LLM for that)
    """
    import re

    facts = []
    msg_lower = message.lower()

    # Height patterns
    height_patterns = [
        r"(\d{2,3})\s*см",
        r"зріст\s*(\d{2,3})",
        r"ріст\s*(\d{2,3})",
    ]
    for pattern in height_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            height = int(match.group(1))
            if 70 <= height <= 180:
                facts.append({
                    "content": f"Зріст дитини: {height} см",
                    "fact_type": "child_info",
                    "category": "child",
                    "extracted_value": height,
                    "field": "height_cm",
                })
                break

    # Age patterns
    age_patterns = [
        r"(\d{1,2})\s*рок",
        r"(\d{1,2})\s*років",
        r"доньці\s*(\d{1,2})",
        r"синові\s*(\d{1,2})",
        r"дитині\s*(\d{1,2})",
    ]
    for pattern in age_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            age = int(match.group(1))
            if 0 <= age <= 18:
                facts.append({
                    "content": f"Вік дитини: {age} років",
                    "fact_type": "child_info",
                    "category": "child",
                    "extracted_value": age,
                    "field": "age",
                })
                break

    # Gender patterns (all Ukrainian cases/forms)
    girl_words = [
        "донька", "доньки", "доньці", "доньку", "донькою",
        "дочка", "дочки", "дочці", "дочку", "дочкою",
        "дівчинка", "дівчинки", "дівчинці", "дівчинку", "дівчинкою",
        "дівчини", "дівчині", "дівчину", "дівчиною",
    ]
    boy_words = [
        "син", "сина", "сину", "синові", "сином",
        "хлопчик", "хлопчика", "хлопчику", "хлопчиком",
        "хлопця", "хлопцю", "хлопцем",
    ]

    if any(word in msg_lower for word in girl_words):
        facts.append({
            "content": "Стать: дівчинка",
            "fact_type": "child_info",
            "category": "child",
            "extracted_value": "дівчинка",
            "field": "gender",
        })
    elif any(word in msg_lower for word in boy_words):
        facts.append({
            "content": "Стать: хлопчик",
            "fact_type": "child_info",
            "category": "child",
            "extracted_value": "хлопчик",
            "field": "gender",
        })

    # City patterns (major Ukrainian cities with all cases/forms)
    # Format: (canonical, [variations])
    city_variations = [
        ("Київ", ["київ", "києва", "києві", "київі", "києву"]),
        ("Харків", ["харків", "харкова", "харкові", "харкову"]),
        ("Одеса", ["одеса", "одеси", "одесі", "одесу", "одесою"]),
        ("Дніпро", ["дніпро", "дніпра", "дніпрі", "дніпру"]),
        ("Львів", ["львів", "львова", "львові", "львову"]),
        ("Запоріжжя", ["запоріжжя", "запоріжжі", "запоріжжю"]),
        ("Кривий Ріг", ["кривий ріг", "кривого рогу", "кривому розі"]),
        ("Миколаїв", ["миколаїв", "миколаєва", "миколаєві"]),
        ("Вінниця", ["вінниця", "вінниці", "вінницю"]),
        ("Херсон", ["херсон", "херсона", "херсоні", "херсону"]),
        ("Полтава", ["полтава", "полтави", "полтаві", "полтаву"]),
        ("Чернігів", ["чернігів", "чернігова", "чернігові"]),
        ("Черкаси", ["черкаси", "черкас", "черкасах"]),
        ("Житомир", ["житомир", "житомира", "житомирі"]),
        ("Суми", ["суми", "сум", "сумах", "сумі"]),
        ("Рівне", ["рівне", "рівного", "рівному"]),
        ("Тернопіль", ["тернопіль", "тернополя", "тернополі"]),
        ("Луцьк", ["луцьк", "луцька", "луцьку"]),
        ("Ужгород", ["ужгород", "ужгорода", "ужгороді"]),
        ("Хмельницький", ["хмельницький", "хмельницького", "хмельницькому"]),
        ("Івано-Франківськ", ["івано-франківськ", "івано-франківська", "івано-франківську"]),
    ]

    for canonical, variations in city_variations:
        if any(var in msg_lower for var in variations):
            facts.append({
                "content": f"Місто: {canonical}",
                "fact_type": "logistics",
                "category": "delivery",
                "extracted_value": canonical,
                "field": "city",
            })
            break

    return facts
