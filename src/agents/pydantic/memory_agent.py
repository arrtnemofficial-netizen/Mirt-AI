"""
Memory Agent - Fact classification and quick extraction.
========================================================
Keeps internal memory context clean and structured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.services.domain.memory.memory_models import Fact, MemoryDecision, UserProfile
from src.conf.config import settings
from src.core.prompt_registry import registry
from src.services.domain.memory.memory_config import (
    get_memory_label,
    get_memory_patterns,
    get_memory_template,
)


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


_MEMORY_PROMPT_FALLBACK = (
    "You are a memory analyzer. Extract facts that help personalization and ignore noise."
)


def _get_memory_prompt() -> str:
    """Get memory prompt from .md file with fallback."""
    try:
        base_identity = registry.get("system.base_identity").content
        domain_prompt = registry.get("memory.main").content
        return f"{base_identity}\n\n{domain_prompt}"
    except Exception as e:
        logger.warning("Failed to load memory.main, using fallback: %s", e)
        return _MEMORY_PROMPT_FALLBACK


# =============================================================================
# DYNAMIC PROMPTS
# =============================================================================


async def _add_profile_context(ctx: RunContext[MemoryDeps]) -> str:
    """Add current profile to the prompt."""
    profile = ctx.deps.profile
    if not profile:
        return "\n--- PROFILE CONTEXT: NONE ---"

    lines = ["\n--- PROFILE CONTEXT ---"]

    # Child info
    child = profile.child_profile
    if child.height_cm or child.age:
        child_info = []
        if child.name:
            child_info.append(f"name: {child.name}")
        if child.age:
            child_info.append(f"age: {child.age}")
        if child.height_cm:
            child_info.append(f"height_cm: {child.height_cm}")
        if child.gender:
            child_info.append(f"gender: {child.gender}")
        lines.append(f"child: {', '.join(child_info)}")

    # Style
    style = profile.style_preferences
    if style.favorite_models:
        lines.append(f"favorite_models: {', '.join(style.favorite_models)}")
    if style.favorite_colors:
        lines.append(f"favorite_colors: {', '.join(style.favorite_colors)}")
    if style.avoided_colors:
        lines.append(f"avoided_colors: {', '.join(style.avoided_colors)}")

    # Logistics
    logistics = profile.logistics
    if logistics.city:
        lines.append(f"city: {logistics.city}")
    if logistics.favorite_branch:
        lines.append(f"branch: {logistics.favorite_branch}")

    # Commerce
    commerce = profile.commerce
    if commerce.total_orders > 0:
        lines.append(f"total_orders: {commerce.total_orders}")

    if len(lines) == 1:
        lines.append("(no profile attributes)")

    return "\n".join(lines)


async def _add_existing_facts(ctx: RunContext[MemoryDeps]) -> str:
    """Add existing facts for duplicate checks."""
    facts = ctx.deps.existing_facts
    if not facts:
        return "\n--- EXISTING FACTS: NONE ---"

    lines = ["\n--- EXISTING FACTS (for dedupe) ---"]
    for fact in facts[:15]:  # Max 15
        lines.append(
            f"- [{fact.id}] [{fact.category}] {fact.content} (importance={fact.importance:.1f})"
        )

    return "\n".join(lines)


async def _add_messages_to_analyze(ctx: RunContext[MemoryDeps]) -> str:
    """Add recent messages to analyze."""
    messages = ctx.deps.messages_to_analyze
    if not messages:
        return "\n--- MESSAGES TO ANALYZE: NONE ---"

    lines = ["\n--- MESSAGES TO ANALYZE ---"]
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
    """Get or create OpenAI GPT-5.1 model for memory agent."""
    global _memory_model
    if _memory_model is None:
        api_key = settings.OPENAI_API_KEY.get_secret_value()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required. OpenRouter support has been removed.")
        
        base_url = "https://api.openai.com/v1"
        model_name = settings.LLM_MODEL_GPT  # GPT-5.1 only

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
            output_type=MemoryDecision,
            system_prompt=_get_memory_prompt(),
            retries=1,
        )

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
    """Analyze messages and extract memory facts."""
    import asyncio

    agent = get_memory_agent()

    deps = MemoryDeps(
        user_id=user_id,
        session_id=session_id,
        profile=profile,
        existing_facts=existing_facts or [],
        messages_to_analyze=messages,
    )

    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        logger.debug("No user messages to analyze")
        return MemoryDecision(ignore_messages=True, reasoning="No user messages")

    analysis_text = "\n".join(m.get("content", "")[:500] for m in user_messages[-5:])

    try:
        result = await asyncio.wait_for(
            agent.run(
                f"Analyze these messages and extract facts:\n\n{analysis_text}",
                deps=deps,
            ),
            timeout=30,
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
        return MemoryDecision(ignore_messages=True, reasoning="Timeout during analysis")

    except Exception as e:
        logger.error("Memory agent error for user %s: %s", user_id, e)
        return MemoryDecision(ignore_messages=True, reasoning=f"Error: {str(e)[:100]}")


# =============================================================================
# QUICK FACTS EXTRACTION (without LLM)
# =============================================================================


def extract_quick_facts(message: str) -> list[dict[str, Any]]:
    """Quick regex-based extraction for obvious facts."""
    import re

    patterns = get_memory_patterns()
    height_patterns = patterns.get("height", [])
    age_patterns = patterns.get("age", [])
    gender_patterns = patterns.get("gender", {})
    girl_words = gender_patterns.get("girl", [])
    boy_words = gender_patterns.get("boy", [])
    city_variations = patterns.get("cities", [])

    height_template = get_memory_template("height", "Child height: {height} cm")
    age_template = get_memory_template("age", "Child age: {age}")
    gender_girl_template = get_memory_template("gender_girl", "Gender: girl")
    gender_boy_template = get_memory_template("gender_boy", "Gender: boy")
    city_template = get_memory_template("city", "City: {city}")
    gender_girl_value = get_memory_label("gender_girl", "girl")
    gender_boy_value = get_memory_label("gender_boy", "boy")

    facts: list[dict[str, Any]] = []
    msg_lower = message.lower()

    for pattern in height_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            height = int(match.group(1))
            if 70 <= height <= 180:
                facts.append(
                    {
                        "content": height_template.format(height=height),
                        "fact_type": "child_info",
                        "category": "child",
                        "extracted_value": height,
                        "field": "height_cm",
                    }
                )
                break

    for pattern in age_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            age = int(match.group(1))
            if 0 <= age <= 18:
                facts.append(
                    {
                        "content": age_template.format(age=age),
                        "fact_type": "child_info",
                        "category": "child",
                        "extracted_value": age,
                        "field": "age",
                    }
                )
                break

    if any(word in msg_lower for word in girl_words):
        facts.append(
            {
                "content": gender_girl_template,
                "fact_type": "child_info",
                "category": "child",
                "extracted_value": gender_girl_value,
                "field": "gender",
            }
        )
    elif any(word in msg_lower for word in boy_words):
        facts.append(
            {
                "content": gender_boy_template,
                "fact_type": "child_info",
                "category": "child",
                "extracted_value": gender_boy_value,
                "field": "gender",
            }
        )

    for item in city_variations:
        if not isinstance(item, dict):
            continue
        canonical = item.get("canonical")
        variations = item.get("variations", [])
        if not isinstance(canonical, str) or not isinstance(variations, list):
            continue
        if any(var in msg_lower for var in variations if isinstance(var, str)):
            facts.append(
                {
                    "content": city_template.format(city=canonical),
                    "fact_type": "logistics",
                    "category": "delivery",
                    "extracted_value": canonical,
                    "field": "city",
                }
            )
            break

    return facts
