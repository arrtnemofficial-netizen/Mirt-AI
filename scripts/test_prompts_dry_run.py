#!/usr/bin/env python3
"""
Dry-run тестування промптів та AI шару БЕЗ API ключа.

Цей скрипт дозволяє:
1. Перевірити, що всі промпти правильно завантажуються
2. Подивитися, які промпти будуть відправлені до LLM
3. Протестувати логіку агентів з мок-відповідями
4. Валідувати структуру промптів

Використання:
    python scripts/test_prompts_dry_run.py                    # Перевірка всіх промптів
    python scripts/test_prompts_dry_run.py --agent main       # Тест main agent з мок-відповіддю
    python scripts/test_prompts_dry_run.py --show-prompt      # Показати промпт для конкретного стану
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Add project root to path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

# Disable OpenAI API key requirement
os.environ["OPENAI_API_KEY"] = "test-key-dry-run"
os.environ["CELERY_EAGER"] = "true"


def test_prompt_loading():
    """Перевірка завантаження всіх промптів."""
    print("=" * 80)
    print("📋 ТЕСТ 1: Завантаження промптів")
    print("=" * 80)
    
    from src.core.prompt_registry import PromptRegistry
    from src.core.state_machine import State
    
    registry = PromptRegistry()
    errors = []
    
    # Перевірка системного промпту
    try:
        system_prompt = registry.get("system.main")
        print(f"✅ System prompt: {len(system_prompt.content)} символів")
        # Перевіряємо, що це domain-specific промпт (MIRT_UA, Софія)
        assert "MIRT" in system_prompt.content or "Софія" in system_prompt.content
        assert "Софія" in system_prompt.content
    except Exception as e:
        errors.append(f"System prompt: {e}")
        print(f"❌ System prompt: {e}")
    
    # Перевірка base_identity (core rules)
    try:
        base_identity = registry.get("system.base_identity")
        print(f"✅ Base identity: {len(base_identity.content)} символів")
        assert "IDENTITY" in base_identity.content or "CORE" in base_identity.content
    except Exception as e:
        errors.append(f"Base identity: {e}")
        print(f"❌ Base identity: {e}")
    
    # Перевірка state промптів
    state_errors = []
    for state in State:
        try:
            prompt = registry.get(f"state.{state.value}")
            assert len(prompt.content) > 10, f"State {state.value} is empty"
            assert "## DO" in prompt.content, f"State {state.value} missing DO section"
            print(f"  ✅ {state.value}: {len(prompt.content)} символів")
        except Exception as e:
            state_errors.append(f"{state.value}: {e}")
            print(f"  ❌ {state.value}: {e}")
    
    if state_errors:
        errors.extend(state_errors)
    
    # Перевірка snippets
    try:
        from src.core.prompt_registry import get_snippet_by_header
        # Перевіримо, що snippets доступні через get_snippet_by_header
        test_snippet = get_snippet_by_header("VISION_LABELS")
        if test_snippet:
            print(f"✅ Snippets: доступні через get_snippet_by_header")
        else:
            print(f"⚠️  Snippets: не знайдено тестовий snippet, але система працює")
    except Exception as e:
        errors.append(f"Snippets: {e}")
        print(f"❌ Snippets: {e}")
    
    if errors:
        print(f"\n⚠️  Знайдено {len(errors)} помилок:")
        for err in errors:
            print(f"   - {err}")
        return False
    
    print("\n✅ Всі промпти завантажені успішно!")
    return True


def show_prompt_for_state(state_name: str):
    """Показати промпт для конкретного стану."""
    print("=" * 80)
    print(f"📄 ПРОМПТ ДЛЯ СТАНУ: {state_name}")
    print("=" * 80)
    
    from src.core.prompt_registry import PromptRegistry
    
    registry = PromptRegistry()
    
    try:
        prompt = registry.get(f"state.{state_name}")
        print(prompt.content)
        print("\n" + "=" * 80)
        print(f"Довжина: {len(prompt.content)} символів")
    except Exception as e:
        print(f"❌ Помилка завантаження промпту: {e}")


def show_full_prompt_for_agent(message: str, state: str = "STATE_0_INIT"):
    """Показати повний промпт, який буде відправлений до LLM."""
    print("=" * 80)
    print("🔍 DRY-RUN: Повний промпт для LLM")
    print("=" * 80)
    print(f"Повідомлення користувача: {message}")
    print(f"Поточний стан: {state}")
    print("=" * 80)
    
    from src.agents.pydantic.deps import AgentDeps
    from src.agents.pydantic.main_agent import _get_base_prompt, _get_model
    from src.core.prompt_registry import PromptRegistry
    from src.core.state_machine import State
    
    registry = PromptRegistry()
    
    # Створити мок deps
    deps = AgentDeps(
        session_id="test-session-dry-run",
        customer_name=None,
        customer_phone=None,
        customer_city=None,
        customer_nova_poshta=None,
        current_state=state,
        selected_products=[],
        order_context={},
    )
    
    # Отримати базовий промпт
    try:
        base_prompt = _get_base_prompt()
        print("\n📋 БАЗОВИЙ ПРОМПТ:")
        print("-" * 80)
        print(base_prompt[:500] + "..." if len(base_prompt) > 500 else base_prompt)
        
        # Отримати state-specific промпт
        state_prompt = registry.get(f"state.{state}").content
        print(f"\n📋 STATE-SPECIFIC ПРОМПТ ({state}):")
        print("-" * 80)
        print(state_prompt[:500] + "..." if len(state_prompt) > 500 else state_prompt)
        
        # Показати повідомлення користувача
        print(f"\n💬 ПОВІДОМЛЕННЯ КОРИСТУВАЧА:")
        print("-" * 80)
        print(message)
        
        print("\n" + "=" * 80)
        print("✅ Промпт готовий до відправки (без реального виклику API)")
        
    except Exception as e:
        print(f"❌ Помилка формування промпту: {e}")
        import traceback
        traceback.print_exc()


async def test_agent_with_mock(message: str, agent_type: str = "main"):
    """Тест агента з мок-відповіддю."""
    print("=" * 80)
    print(f"🤖 ТЕСТ 2: {agent_type.upper()} Agent з мок-відповіддю")
    print("=" * 80)
    print(f"Повідомлення: {message}")
    print("=" * 80)
    
    from unittest.mock import AsyncMock, patch
    from src.agents.pydantic.deps import AgentDeps
    from src.agents.pydantic.models import (
        MessageItem,
        ResponseMetadata,
        SupportResponse,
    )
    
    # Створити мок deps
    deps = AgentDeps(
        session_id="test-session-mock",
        customer_name=None,
        customer_phone=None,
        customer_city=None,
        customer_nova_poshta=None,
        current_state="STATE_0_INIT",
        selected_products=[],
        order_context={},
    )
    
    # Мок-відповідь
    mock_response = SupportResponse(
        event="simple_answer",
        messages=[MessageItem(type="text", content="Привіт! Це тестова відповідь без API.")],
        metadata=ResponseMetadata(
            session_id=deps.session_id,
            current_state="STATE_1_DISCOVERY",
            intent="GREETING_ONLY",
            escalation_level="NONE",
        ),
    )
    
    if agent_type == "main":
        # Просто показуємо, який промпт буде використаний
        # Без реального виклику API
        print("\n📋 ПРОМПТ, ЯКИЙ БУДЕ ВИКОРИСТАНО:")
        print("-" * 80)
        show_full_prompt_for_agent(message, "STATE_0_INIT")
        
        print("\n✅ Мок-відповідь (як би повернув агент):")
        print(f"   Event: {mock_response.event}")
        print(f"   State: {mock_response.metadata.current_state}")
        print(f"   Intent: {mock_response.metadata.intent}")
        print(f"   Messages: {len(mock_response.messages)}")
        if mock_response.messages:
            print(f"   Перше повідомлення: {mock_response.messages[0].content}")
        
        print("\n💡 Для реального тестування з мок-відповіддю використовуй:")
        print("   pytest tests/test_nodes.py::test_agent_node_returns_valid_state")
        return True
    else:
        print(f"❌ Невідомий тип агента: {agent_type}")
        return False


def validate_prompt_structure():
    """Валідація структури промптів."""
    print("=" * 80)
    print("🔍 ТЕСТ 3: Валідація структури промптів")
    print("=" * 80)
    
    from src.core.prompt_registry import PromptRegistry
    from src.core.state_machine import State
    
    registry = PromptRegistry()
    errors = []
    
    # Перевірка base_identity (core rules)
    base_identity = registry.get("system.base_identity").content
    required_core_sections = ["IDENTITY", "DO NOT"]
    for section in required_core_sections:
        if section not in base_identity:
            errors.append(f"Base identity missing section: {section}")
    
    # Перевірка системного промпту (domain-specific, не потребує core секцій)
    system_prompt = registry.get("system.main").content
    required_domain_sections = ["MIRT", "Софія"]
    for section in required_domain_sections:
        if section not in system_prompt:
            errors.append(f"System prompt missing domain section: {section}")
    
    # Перевірка state промптів
    for state in State:
        try:
            prompt = registry.get(f"state.{state.value}").content
            if "## DO" not in prompt:
                errors.append(f"{state.value} missing DO section")
            if "## TRANSITIONS" not in prompt:
                errors.append(f"{state.value} missing TRANSITIONS section")
        except Exception as e:
            errors.append(f"{state.value}: {e}")
    
    if errors:
        print(f"⚠️  Знайдено {len(errors)} проблем:")
        for err in errors:
            print(f"   - {err}")
        return False
    
    print("✅ Всі промпти мають правильну структуру!")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Dry-run тестування промптів без API ключа")
    parser.add_argument("--agent", choices=["main", "offer", "vision"], help="Тест конкретного агента")
    parser.add_argument("--message", default="Привіт", help="Тестове повідомлення")
    parser.add_argument("--state", help="Показати промпт для конкретного стану")
    parser.add_argument("--show-prompt", action="store_true", help="Показати повний промпт для LLM")
    parser.add_argument("--validate-only", action="store_true", help="Тільки валідація, без тестів")
    
    args = parser.parse_args()
    
    # Тест 1: Завантаження промптів
    if not test_prompt_loading():
        sys.exit(1)
    
    if args.validate_only:
        validate_prompt_structure()
        return
    
    # Показати промпт для стану
    if args.state:
        show_prompt_for_state(args.state)
        return
    
    # Показати повний промпт
    if args.show_prompt:
        show_full_prompt_for_agent(args.message, args.state or "STATE_0_INIT")
        return
    
    # Валідація структури
    if not validate_prompt_structure():
        sys.exit(1)
    
    # Тест агента з мок-відповіддю
    if args.agent:
        success = await test_agent_with_mock(args.message, args.agent)
        if not success:
            sys.exit(1)
    
    print("\n" + "=" * 80)
    print("✅ ВСІ ТЕСТИ ПРОЙДЕНО БЕЗ API КЛЮЧА!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

