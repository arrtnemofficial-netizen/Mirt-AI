"""
Memory Models - Titans-like Memory System для MIRT AI.
========================================================
Типізовані моделі для 3-рівневої архітектури памʼяті:
  1. UserProfile (Persistent Memory)
  2. Fact/NewFact/UpdateFact (Fluid Memory)
  3. MemorySummary (Compressed Memory)

MemoryDecision - output від MemoryAgent з importance/surprise метриками.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# FACT TYPES & CATEGORIES
# =============================================================================

FactType = Literal[
    "preference",   # Вподобання (колір, стиль, модель)
    "constraint",   # Обмеження (алергія, не носить синтетику)
    "logistics",    # Логістика (місто, НП, адреса)
    "behavior",     # Поведінка (часто повертає, завжди купує акційне)
    "feedback",     # Зворотний звʼязок (скарги, похвала)
    "child_info",   # Інфо про дитину (вік, зріст, стать)
]

FactCategory = Literal[
    "child",        # Інфо про дитину
    "style",        # Стиль і вподобання
    "delivery",     # Доставка
    "payment",      # Оплата
    "product",      # Конкретний товар
    "complaint",    # Скарги
    "general",      # Загальне
]


# =============================================================================
# 1. PERSISTENT MEMORY - User Profile Models
# =============================================================================


class ChildProfile(BaseModel):
    """Профіль дитини (для дитячого одягу)."""

    name: str | None = Field(default=None, description="Імʼя дитини")
    age: int | None = Field(default=None, ge=0, le=18, description="Вік дитини")
    height_cm: int | None = Field(default=None, ge=50, le=200, description="Зріст в см")
    height_history: list[dict] = Field(
        default_factory=list,
        description="Історія змін зросту: [{date: '2024-01', height: 122}]"
    )
    body_type: Literal["стандартна", "худорлява", "повненька"] | None = Field(
        default=None, description="Тип статури"
    )
    gender: Literal["хлопчик", "дівчинка"] | None = Field(
        default=None, description="Стать дитини"
    )


class StylePreferences(BaseModel):
    """Вподобання щодо стилю."""

    favorite_models: list[str] = Field(
        default_factory=list,
        description="Улюблені моделі: ['Лагуна', 'Ритм', 'Веселка']"
    )
    preferred_styles: list[str] = Field(
        default_factory=list,
        description="Улюблені стилі: ['спортивний', 'святковий']"
    )
    favorite_colors: list[str] = Field(
        default_factory=list,
        description="Улюблені кольори"
    )
    avoided_colors: list[str] = Field(
        default_factory=list,
        description="Кольори яких уникає"
    )
    fabric_preferences: list[str] = Field(
        default_factory=list,
        description="Вподобання тканин: ['бавовна', 'не синтетика']"
    )


class LogisticsInfo(BaseModel):
    """Інформація про доставку."""

    city: str | None = Field(default=None, description="Місто")
    delivery_type: Literal["nova_poshta", "ukrposhta", "courier", "self_pickup"] | None = Field(
        default=None, description="Тип доставки"
    )
    favorite_branch: str | None = Field(
        default=None, description="Улюблене відділення НП"
    )
    address: str | None = Field(default=None, description="Адреса для курʼєра")


class CommerceInfo(BaseModel):
    """Комерційна поведінка клієнта."""

    avg_check: float | None = Field(default=None, ge=0, description="Середній чек")
    order_frequency: Literal["first_time", "rare", "monthly", "frequent"] | None = Field(
        default=None, description="Частота замовлень"
    )
    discount_sensitive: bool = Field(default=False, description="Чутливий до знижок")
    payment_preference: Literal["card_online", "card_on_delivery", "cash"] | None = Field(
        default=None, description="Улюблений спосіб оплати"
    )
    total_orders: int = Field(default=0, ge=0, description="Всього замовлень")
    last_order_date: str | None = Field(default=None, description="Дата останнього замовлення")


class UserProfile(BaseModel):
    """
    Persistent Memory - повний профіль користувача.
    
    Це те, що завантажується ЗАВЖДИ перед кожною сесією.
    Аналог Persistent Memory в Titans: те, що майже ніколи не забувається.
    """

    user_id: str = Field(description="External ID (Telegram/ManyChat/Instagram)")

    child_profile: ChildProfile = Field(default_factory=ChildProfile)
    style_preferences: StylePreferences = Field(default_factory=StylePreferences)
    logistics: LogisticsInfo = Field(default_factory=LogisticsInfo)
    commerce: CommerceInfo = Field(default_factory=CommerceInfo)

    # Metadata
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    last_seen_at: datetime | None = Field(default=None)
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# 2. FLUID MEMORY - Facts with Importance/Surprise
# =============================================================================


class Fact(BaseModel):
    """
    Атомарний факт з Fluid Memory.
    
    Ключові метрики для Titans-like gating:
    - importance: наскільки факт впливає на рекомендації (0-1)
    - surprise: наскільки це нова інформація (0-1)
    """

    id: UUID | None = Field(default=None, description="UUID факту (None для нових)")
    user_id: str = Field(description="ID користувача")
    session_id: str | None = Field(default=None, description="ID сесії (опц.)")

    content: str = Field(description="Текст факту")
    fact_type: FactType = Field(description="Тип факту")
    category: FactCategory = Field(description="Категорія факту")

    # Titans-like metrics
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Вплив на рекомендації (0=ігнорувати, 1=критичний)"
    )
    surprise: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Новизна (0=очікувано, 1=дуже неочікувано)"
    )
    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0,
        description="Впевненість у факті"
    )

    # Time-based
    ttl_days: int | None = Field(
        default=None,
        description="Через скільки днів видалити (None = вічний)"
    )

    # Lifecycle
    created_at: datetime | None = Field(default=None)
    last_accessed_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True)


class NewFact(BaseModel):
    """
    Новий факт для запису в память.
    
    MemoryAgent генерує це коли знаходить НОВУ інформацію.
    Gating rule: записуємо тільки якщо importance >= 0.6 AND surprise >= 0.4
    """

    content: str = Field(description="Текст факту")
    fact_type: FactType = Field(description="preference/constraint/logistics/behavior/feedback/child_info")
    category: FactCategory = Field(description="child/style/delivery/payment/product/complaint/general")

    importance: float = Field(
        ge=0.0, le=1.0,
        description="0-1: наскільки впливає на рекомендації"
    )
    surprise: float = Field(
        ge=0.0, le=1.0,
        description="0-1: наскільки це нова інформація"
    )

    ttl_days: int | None = Field(
        default=None,
        description="Через скільки днів видалити (None = вічний)"
    )

    @field_validator("importance", "surprise")
    @classmethod
    def validate_range(cls, v: float) -> float:
        return round(v, 2)


class UpdateFact(BaseModel):
    """
    Оновлення існуючого факту.
    
    MemoryAgent генерує це коли КОНФЛІКТ:
    - Нове місто (переїхали)
    - Новий зріст дитини (виросла)
    - Змінились вподобання
    """

    fact_id: UUID = Field(description="ID існуючого факту для оновлення")
    new_content: str = Field(description="Новий текст факту")

    importance: float = Field(
        ge=0.0, le=1.0,
        description="Нова важливість"
    )
    surprise: float = Field(
        ge=0.0, le=1.0,
        description="Surprise що факт змінився"
    )


class DeleteFact(BaseModel):
    """Запит на видалення факту."""

    fact_id: UUID = Field(description="ID факту для видалення")
    reason: str = Field(description="Причина видалення")


# =============================================================================
# 3. MEMORY DECISION - Output від MemoryAgent
# =============================================================================


class MemoryDecision(BaseModel):
    """
    Output від MemoryAgent.
    
    MemoryAgent аналізує діалог і вирішує:
    - Які нові факти запамʼятати
    - Які існуючі факти оновити
    - Що можна проігнорувати
    
    Це прикладний аналог Titans Surprise Metric + Gating.
    """

    new_facts: list[NewFact] = Field(
        default_factory=list,
        description="Нові факти для запису"
    )

    updates: list[UpdateFact] = Field(
        default_factory=list,
        description="Оновлення існуючих фактів"
    )

    deletes: list[DeleteFact] = Field(
        default_factory=list,
        description="Факти для видалення"
    )

    profile_updates: dict = Field(
        default_factory=dict,
        description="Оновлення до профілю (child_profile, style_preferences, etc.)"
    )

    ignore_messages: bool = Field(
        default=False,
        description="True якщо повідомлення не містять нової інформації"
    )

    reasoning: str | None = Field(
        default=None,
        description="Пояснення рішень (для debug)"
    )


# =============================================================================
# 4. COMPRESSED MEMORY - Summaries
# =============================================================================


class MemorySummary(BaseModel):
    """
    Summary для зменшення токенів в промпті.
    
    Замість 100 фактів даємо 2-3 стислі блоки.
    """

    summary_type: Literal["user", "product", "session"] = Field(
        description="Тип summary"
    )

    summary_text: str = Field(
        description="Стислий текст summary"
    )

    key_facts: list[str] = Field(
        default_factory=list,
        description="Ключові факти (для quick access)"
    )

    facts_count: int = Field(
        default=0, ge=0,
        description="Скільки фактів узагальнено"
    )

    is_current: bool = Field(
        default=True,
        description="Чи це актуальний summary"
    )


# =============================================================================
# 5. MEMORY CONTEXT - Input для агентів
# =============================================================================


class MemoryContext(BaseModel):
    """
    Контекст памʼяті для передачі в агенти.
    
    Це те, що додається до промпта перед кожним викликом агента:
    - profile: persistent memory
    - facts: top-K fluid memories
    - summary: compressed context
    """

    profile: UserProfile | None = Field(
        default=None,
        description="Профіль користувача (Persistent Memory)"
    )

    facts: list[Fact] = Field(
        default_factory=list,
        description="Релевантні факти (Fluid Memory, top-K)"
    )

    summary: MemorySummary | None = Field(
        default=None,
        description="Summary (Compressed Memory)"
    )

    def to_prompt_block(self) -> str:
        """
        Форматує контекст памʼяті для вставки в промпт.
        
        Returns:
            Форматований текст для system/state prompt
        """
        lines = ["### ЩО МИ ЗНАЄМО ПРО КЛІЄНТА:"]

        if self.profile:
            p = self.profile

            # Child info
            if p.child_profile.height_cm or p.child_profile.age:
                child_info = []
                if p.child_profile.name:
                    child_info.append(f"імʼя: {p.child_profile.name}")
                if p.child_profile.age:
                    child_info.append(f"вік: {p.child_profile.age} років")
                if p.child_profile.height_cm:
                    child_info.append(f"зріст: {p.child_profile.height_cm} см")
                if p.child_profile.gender:
                    child_info.append(f"стать: {p.child_profile.gender}")
                if p.child_profile.body_type:
                    child_info.append(f"статура: {p.child_profile.body_type}")
                if child_info:
                    lines.append(f"- Дитина: {', '.join(child_info)}")

            # Style
            if p.style_preferences.favorite_models:
                lines.append(f"- Улюблені моделі: {', '.join(p.style_preferences.favorite_models)}")
            if p.style_preferences.favorite_colors:
                lines.append(f"- Улюблені кольори: {', '.join(p.style_preferences.favorite_colors)}")
            if p.style_preferences.avoided_colors:
                lines.append(f"- Уникає кольорів: {', '.join(p.style_preferences.avoided_colors)}")

            # Logistics
            if p.logistics.city:
                lines.append(f"- Місто: {p.logistics.city}")
            if p.logistics.favorite_branch:
                lines.append(f"- Відділення НП: {p.logistics.favorite_branch}")

            # Commerce
            if p.commerce.total_orders > 0:
                lines.append(f"- Постійний клієнт: {p.commerce.total_orders} замовлень")
            if p.commerce.avg_check:
                lines.append(f"- Середній чек: {p.commerce.avg_check:.0f} грн")

        # Facts - limit to most important to save tokens
        # Limiting to 3 facts also helps with context window efficiency
        MAX_FACTS = 3
        MAX_FACT_LENGTH = 50  # Enough for typical facts like "Улюблений колір рожевий"

        if self.facts:
            lines.append("\n### ВАЖЛИВІ ФАКТИ:")
            for fact in self.facts[:MAX_FACTS]:
                # Truncate long content to prevent token overflow
                content = fact.content
                if len(content) > MAX_FACT_LENGTH:
                    # Try to cut at word boundary, else hard cut
                    truncated = content[:MAX_FACT_LENGTH]
                    space_idx = truncated.rfind(' ')
                    if space_idx > MAX_FACT_LENGTH // 2:
                        content = truncated[:space_idx] + "..."
                    else:
                        content = truncated + "..."
                lines.append(f"- [{fact.category}] {content}")

        # Summary
        if self.summary and self.summary.summary_text:
            lines.append(f"\n### SUMMARY: {self.summary.summary_text}")

        if len(lines) == 1:  # Only header
            return ""  # No memory context

        # Limit total prompt length to save tokens
        MAX_PROMPT_LENGTH = 1500
        result = "\n".join(lines)

        if len(result) > MAX_PROMPT_LENGTH:
            # Truncate at line boundary
            lines_to_keep = []
            current_length = 0
            for line in lines:
                if current_length + len(line) + 1 > MAX_PROMPT_LENGTH:
                    break
                lines_to_keep.append(line)
                current_length += len(line) + 1
            result = "\n".join(lines_to_keep)
            if len(lines_to_keep) < len(lines):
                result += "\n..."

        return result

    def is_empty(self) -> bool:
        """Перевіряє чи є хоч якийсь контекст."""
        has_profile = self.profile and (
            self.profile.child_profile.height_cm or
            self.profile.logistics.city or
            self.profile.commerce.total_orders > 0
        )
        return not has_profile and not self.facts and not self.summary
