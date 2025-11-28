#!/usr/bin/env python
"""Real LLM Integration Tests - Uses actual API keys.

This script tests the full AI pipeline with real LLM calls.
Requires valid OPENROUTER_API_KEY or OPENAI_API_KEY in .env

Usage:
    python scripts/test_real_llm.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv


load_dotenv()


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def print_result(success: bool, message: str) -> None:
    icon = "✅" if success else "❌"
    print(f"{icon} {message}")


async def test_agent_response():
    """Test 1: Direct agent call with real LLM."""
    print_header("TEST 1: Direct Agent Call (LLM)")

    from src.agents.graph_v2 import get_active_graph
    from src.conf.config import settings

    print(f"  LLM Provider: {settings.LLM_PROVIDER}")
    print(f"  Model: {settings.AI_MODEL}")

    graph = get_active_graph()

    # Test message
    test_input = {
        "messages": [
            {"role": "user", "content": "Привіт! Шукаю червону сукню для дівчинки 5 років."}
        ],
        "metadata": {
            "session_id": "test_real_llm",
            "current_state": "STATE_1_DISCOVERY",
        },
    }

    print("\n  Input: 'Привіт! Шукаю червону сукню для дівчинки 5 років.'")
    print("  Calling LLM...")

    start = datetime.now(UTC)
    try:
        result = await graph.ainvoke(test_input)
        elapsed = (datetime.now(UTC) - start).total_seconds()

        # Extract response
        response_text = ""
        if result and "messages" in result:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content"):
                response_text = last_msg.content
            elif isinstance(last_msg, dict):
                response_text = last_msg.get("content", "")

        print(f"\n  Response ({elapsed:.2f}s):")
        print(f"  ---")
        # Truncate long response
        display = response_text[:300] + "..." if len(response_text) > 300 else response_text
        for line in display.split("\n"):
            print(f"    {line}")
        print(f"  ---")

        print_result(True, f"Agent responded in {elapsed:.2f}s ({len(response_text)} chars)")
        return True

    except Exception as e:
        print_result(False, f"Agent failed: {e}")
        return False


def get_response_text(response) -> str:
    """Extract text from AgentResponse messages."""
    if hasattr(response, "messages") and response.messages:
        return " ".join(m.content for m in response.messages if m.content)
    return str(response)


async def test_conversation_handler():
    """Test 2: Full conversation handler with message store."""
    print_header("TEST 2: Conversation Handler")

    from src.agents.graph_v2 import get_active_graph
    from src.services.conversation import create_conversation_handler
    from src.services.message_store import create_message_store
    from src.services.session_store import InMemorySessionStore

    session_store = InMemorySessionStore()
    message_store = create_message_store()
    graph = get_active_graph()

    handler = create_conversation_handler(
        session_store=session_store,
        message_store=message_store,
        runner=graph,
    )

    session_id = f"test_conv_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Message 1
    print(f"\n  Session: {session_id}")
    print("  Message 1: 'Привіт!'")

    start = datetime.now(UTC)
    result1 = await handler.process_message(session_id, "Привіт!")
    elapsed1 = (datetime.now(UTC) - start).total_seconds()

    text1 = get_response_text(result1.response)
    print(f"  Response 1 ({elapsed1:.2f}s): {text1[:100]}...")
    print(f"  State: {result1.response.metadata.current_state}")

    # Message 2
    print("\n  Message 2: 'Шукаю сукню на випускний, розмір 134'")

    start = datetime.now(UTC)
    result2 = await handler.process_message(session_id, "Шукаю сукню на випускний, розмір 134")
    elapsed2 = (datetime.now(UTC) - start).total_seconds()

    text2 = get_response_text(result2.response)
    print(f"  Response 2 ({elapsed2:.2f}s): {text2[:100]}...")
    print(f"  State: {result2.response.metadata.current_state}")
    print(f"  Products: {len(result2.response.products)}")

    # Check history
    history = message_store.list(session_id)
    print(f"\n  Messages in store: {len(history)}")

    print_result(True, f"Conversation handled: 2 turns, {len(history)} messages stored")
    return True


async def test_pydantic_agent_direct():
    """Test 3: Direct Pydantic AI agent call via AgentRunner."""
    print_header("TEST 3: Pydantic AI Agent Direct")

    from src.agents.pydantic_agent import build_agent_runner

    runner = build_agent_runner()

    history = [{"role": "user", "content": "Покажи мені костюми для хлопчика 7 років"}]
    metadata = {
        "session_id": "test_pydantic",
        "current_state": "STATE_1_DISCOVERY",
    }

    print("  Input: 'Покажи мені костюми для хлопчика 7 років'")
    print("  Calling Pydantic AI agent...")

    start = datetime.now(UTC)
    try:
        response = await runner.run(history, metadata)
        elapsed = (datetime.now(UTC) - start).total_seconds()

        text = get_response_text(response)
        print(f"\n  Response ({elapsed:.2f}s):")
        print(f"  Text: {text[:150]}...")
        print(f"  State: {response.metadata.current_state}")
        print(f"  Products: {len(response.products)}")

        if response.products:
            print(f"  First product: {response.products[0].name}")

        print_result(True, f"Pydantic agent responded in {elapsed:.2f}s")
        return True

    except Exception as e:
        print_result(False, f"Pydantic agent failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_celery_dispatcher_sync():
    """Test 4: Dispatcher in sync mode (CELERY_ENABLED=false)."""
    print_header("TEST 4: Dispatcher (Sync Mode)")

    from src.conf.config import settings
    from src.workers.dispatcher import dispatch_followup, dispatch_summarization

    print(f"  CELERY_ENABLED: {settings.CELERY_ENABLED}")

    # Test summarization dispatch
    result = dispatch_summarization("test_session_123")
    print(f"  dispatch_summarization: queued={result.get('queued')}")

    # Test followup dispatch
    result = dispatch_followup("test_session_123")
    print(f"  dispatch_followup: queued={result.get('queued')}")

    print_result(True, "Dispatcher works in sync mode")
    return True


async def test_message_store_real():
    """Test 5: Real message store with Supabase."""
    print_header("TEST 5: Message Store (Supabase)")

    from src.conf.config import settings
    from src.services.message_store import StoredMessage, create_message_store

    print(f"  Supabase URL: {settings.SUPABASE_URL[:40]}...")

    store = create_message_store()
    session_id = f"test_store_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Create message
    msg = StoredMessage(
        session_id=session_id,
        role="user",
        content="Test message from real LLM test",
        created_at=datetime.now(UTC),
    )

    # Append
    store.append(msg)
    print(f"  Appended message to session: {session_id}")

    # List
    messages = store.list(session_id)
    print(f"  Listed messages: {len(messages)}")

    # Cleanup
    if hasattr(store, "delete"):
        store.delete(session_id)
        print("  Cleaned up test messages")

    print_result(len(messages) > 0, f"Message store: {len(messages)} messages")
    return len(messages) > 0


async def test_full_flow():
    """Test 6: Full end-to-end flow."""
    print_header("TEST 6: Full End-to-End Flow")

    from src.agents.graph_v2 import get_active_graph
    from src.services.conversation import create_conversation_handler
    from src.services.message_store import create_message_store
    from src.services.session_store import InMemorySessionStore

    session_store = InMemorySessionStore()
    message_store = create_message_store()
    graph = get_active_graph()

    handler = create_conversation_handler(
        session_store=session_store,
        message_store=message_store,
        runner=graph,
    )

    session_id = f"e2e_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Simulate real conversation
    messages = [
        "Привіт!",
        "Шукаю плаття для дівчинки на день народження",
        "Розмір 128, бюджет до 2000 грн",
        "Покажи рожеві варіанти",
    ]

    print(f"  Session: {session_id}")
    print(f"  Simulating {len(messages)} messages...\n")

    total_time = 0
    for i, msg in enumerate(messages, 1):
        print(f"  [{i}] User: {msg}")

        start = datetime.now(UTC)
        result = await handler.process_message(session_id, msg)
        elapsed = (datetime.now(UTC) - start).total_seconds()
        total_time += elapsed

        # Show truncated response
        text = get_response_text(result.response)[:80].replace("\n", " ")
        print(f"      Bot ({elapsed:.1f}s): {text}...")
        print(
            f"      State: {result.response.metadata.current_state}, Products: {len(result.response.products)}"
        )
        print()

    # Final stats
    history = message_store.list(session_id)
    print(f"  ---")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Messages stored: {len(history)}")
    print(f"  Average response: {total_time / len(messages):.1f}s")

    # Cleanup
    if hasattr(message_store, "delete"):
        message_store.delete(session_id)

    print_result(True, f"E2E flow completed: {len(messages)} turns in {total_time:.1f}s")
    return True


async def main():
    """Run all real LLM tests."""
    print("\n" + "=" * 60)
    print("        🚀 MIRT AI - Real LLM Integration Tests 🚀")
    print("=" * 60)
    print(f"Time: {datetime.now(UTC).isoformat()}")

    # Check API key
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n❌ ERROR: No API key found!")
        print("   Set OPENROUTER_API_KEY or OPENAI_API_KEY in .env")
        return

    print(f"API Key: {api_key[:10]}...{api_key[-4:]}")

    results = {}

    # Run tests
    try:
        results["Agent Response"] = await test_agent_response()
    except Exception as e:
        print_result(False, f"Agent Response: {e}")
        results["Agent Response"] = False

    try:
        results["Conversation Handler"] = await test_conversation_handler()
    except Exception as e:
        print_result(False, f"Conversation Handler: {e}")
        results["Conversation Handler"] = False

    try:
        results["Pydantic Agent"] = await test_pydantic_agent_direct()
    except Exception as e:
        print_result(False, f"Pydantic Agent: {e}")
        results["Pydantic Agent"] = False

    try:
        results["Dispatcher Sync"] = await test_celery_dispatcher_sync()
    except Exception as e:
        print_result(False, f"Dispatcher: {e}")
        results["Dispatcher Sync"] = False

    try:
        results["Message Store"] = await test_message_store_real()
    except Exception as e:
        print_result(False, f"Message Store: {e}")
        results["Message Store"] = False

    try:
        results["Full E2E Flow"] = await test_full_flow()
    except Exception as e:
        print_result(False, f"Full E2E: {e}")
        results["Full E2E Flow"] = False

    # Summary
    print_header("SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, success in results.items():
        print_result(success, name)

    print(f"\n  Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n  🎉 All tests PASSED!")
    else:
        print(f"\n  ⚠️  {total - passed} tests failed")


if __name__ == "__main__":
    asyncio.run(main())
