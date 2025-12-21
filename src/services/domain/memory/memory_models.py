"""
Memory domain models.
Shared by MemoryService and MemoryAgent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChildProfile(BaseModel):
    name: str | None = None
    age: int | None = None
    height_cm: int | None = None
    gender: str | None = None


class StylePreferences(BaseModel):
    favorite_models: list[str] = Field(default_factory=list)
    favorite_colors: list[str] = Field(default_factory=list)
    avoided_colors: list[str] = Field(default_factory=list)
    preferred_styles: list[str] = Field(default_factory=list)
    fabric_preferences: list[str] = Field(default_factory=list)


class LogisticsInfo(BaseModel):
    city: str | None = None
    favorite_branch: str | None = None


class CommerceInfo(BaseModel):
    total_orders: int = 0
    last_order_at: str | None = None


class UserProfile(BaseModel):
    user_id: str
    child_profile: ChildProfile = Field(default_factory=ChildProfile)
    style_preferences: StylePreferences = Field(default_factory=StylePreferences)
    logistics: LogisticsInfo = Field(default_factory=LogisticsInfo)
    commerce: CommerceInfo = Field(default_factory=CommerceInfo)
    created_at: str | None = None
    updated_at: str | None = None
    last_seen_at: str | None = None
    completeness_score: float = 0.0


class Fact(BaseModel):
    id: str | None = None
    user_id: str = ""
    session_id: str | None = None
    content: str
    fact_type: str = "preference"
    category: str = "general"
    importance: float = 0.5
    surprise: float = 0.5
    confidence: float = 0.8
    ttl_days: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_accessed_at: str | None = None
    is_active: bool = True


class NewFact(BaseModel):
    content: str
    fact_type: str = "preference"
    category: str = "general"
    importance: float = 0.5
    surprise: float = 0.5
    confidence: float = 0.8
    ttl_days: int | None = None


class UpdateFact(BaseModel):
    fact_id: str
    new_content: str
    importance: float = 0.5
    surprise: float = 0.5


class DeleteFact(BaseModel):
    fact_id: str
    reason: str = ""


class MemorySummary(BaseModel):
    summary_type: str = "user"
    summary_text: str = ""
    key_facts: list[str] = Field(default_factory=list)
    facts_count: int = 0
    is_current: bool = True


class MemoryContext(BaseModel):
    profile: UserProfile | None = None
    facts: list[Fact] = Field(default_factory=list)
    summary: MemorySummary | None = None

    def is_empty(self) -> bool:
        return not self.profile and not self.facts and not (self.summary and self.summary.summary_text)

    def to_prompt_block(self) -> str:
        lines: list[str] = ["MEMORY CONTEXT"]

        if self.summary and self.summary.summary_text:
            lines.append(f"Summary: {self.summary.summary_text}")

        if self.profile:
            profile = self.profile
            child = profile.child_profile
            style = profile.style_preferences
            logistics = profile.logistics
            commerce = profile.commerce

            lines.append("Profile:")
            if child.name or child.age or child.height_cm or child.gender:
                lines.append(
                    "Child: "
                    + ", ".join(
                        [
                            f"name={child.name}" if child.name else "",
                            f"age={child.age}" if child.age else "",
                            f"height_cm={child.height_cm}" if child.height_cm else "",
                            f"gender={child.gender}" if child.gender else "",
                        ]
                    ).strip(", ")
                )
            if style.favorite_models:
                lines.append(f"Favorite models: {', '.join(style.favorite_models)}")
            if style.favorite_colors:
                lines.append(f"Favorite colors: {', '.join(style.favorite_colors)}")
            if style.avoided_colors:
                lines.append(f"Avoided colors: {', '.join(style.avoided_colors)}")
            if logistics.city:
                lines.append(f"City: {logistics.city}")
            if logistics.favorite_branch:
                lines.append(f"Branch: {logistics.favorite_branch}")
            if commerce.total_orders:
                lines.append(f"Total orders: {commerce.total_orders}")

        if self.facts:
            lines.append("Facts:")
            for fact in self.facts[:20]:
                lines.append(f"- [{fact.category}] {fact.content}")

        return "\n".join(line for line in lines if line)


class MemoryDecision(BaseModel):
    ignore_messages: bool = False
    reasoning: str | None = None
    new_facts: list[NewFact] = Field(default_factory=list)
    updates: list[UpdateFact] = Field(default_factory=list)
    deletes: list[DeleteFact] = Field(default_factory=list)
    profile_updates: dict[str, Any] = Field(default_factory=dict)
