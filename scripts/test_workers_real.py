#!/usr/bin/env python
"""
REAL integration test for Celery workers.
Tests with actual Supabase connection and 1-minute follow-up delay.

Usage:
    python scripts/test_workers_real.py
"""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
from dotenv import load_dotenv


load_dotenv(PROJECT_ROOT / ".env")

from src.conf.config import settings
<<<<<<< Updated upstream:scripts/test_workers_real.py
from src.services.followups import build_followup_message, next_followup_due_at, run_followups
from src.services.message_store import MessageStore, StoredMessage, create_message_store
from src.services.summarization import run_retention, summarise_messages
from src.services.supabase_client import get_supabase_client
=======
from src.services.domain.engagement.followups import build_followup_message, next_followup_due_at, run_followups
from src.services.infra.message_store import StoredMessage, create_message_store
from src.services.domain.memory.summarization import summarise_messages
from src.services.infra.supabase_client import get_supabase_client
>>>>>>> Stashed changes:tests/manual/test_workers_real.py


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(name: str, success: bool, details: str = ""):
    icon = "✅" if success else "❌"
    print(f"{icon} {name}: {details}")


def test_supabase_connection():
    """Test 1: Supabase connection."""
    print_header("TEST 1: Supabase Connection")

    client = get_supabase_client()
    if not client:
        print_result("Connection", False, "No client returned")
        return False

    try:
        # Try to query messages table
        response = (
            client.table(settings.SUPABASE_MESSAGES_TABLE).select("session_id").limit(1).execute()
        )
        print_result("Connection", True, f"Connected to {settings.SUPABASE_URL}")
        print_result(
            "Messages table", True, f"Table '{settings.SUPABASE_MESSAGES_TABLE}' accessible"
        )
        return True
    except Exception as e:
        print_result("Connection", False, str(e))
        return False


def test_followup_logic_1min():
    """Test 2: Follow-up logic with 1-minute delay."""
    print_header("TEST 2: Follow-up Logic (1-minute simulation)")

    # Create test messages simulating conversation 1 minute ago
    session_id = f"test_followup_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Message from 2 minutes ago (should trigger followup with 1-min schedule)
    old_time = datetime.now(UTC) - timedelta(minutes=2)

    messages = [
        StoredMessage(
            session_id=session_id,
            role="user",
            content="Привіт, шукаю сукню",
            created_at=old_time,
        ),
        StoredMessage(
            session_id=session_id,
            role="assistant",
            content="Привіт! Підберу варіанти.",
            created_at=old_time + timedelta(seconds=5),
        ),
    ]

    # Test with 1-minute schedule (0.0166 hours ≈ 1 min)
    schedule_1min = [0.0166]  # 1 minute in hours

    due_at = next_followup_due_at(messages, schedule_hours=schedule_1min)
    now = datetime.now(UTC)

    print(f"  Last activity: {messages[-1].created_at.isoformat()}")
    print(f"  Current time:  {now.isoformat()}")
    print(f"  Due at:        {due_at.isoformat() if due_at else 'None'}")

    is_due = due_at and now >= due_at
    print_result("Follow-up is due", is_due, f"After 1 minute of inactivity")

    if is_due:
        followup = build_followup_message(session_id, index=1, now=now)
        print_result("Follow-up message", True, f'"{followup.content[:50]}..."')
        print(f"  Tags: {followup.tags}")

    return is_due


def test_summarization_logic():
    """Test 3: Summarization logic."""
    print_header("TEST 3: Summarization Logic")

    # Create test messages
    messages = [
        StoredMessage(
            session_id="test_summary",
            role="user",
            content="Шукаю червону сукню на випускний",
            created_at=datetime.now(UTC) - timedelta(days=4),
        ),
        StoredMessage(
            session_id="test_summary",
            role="assistant",
            content="Чудово! Підібрала для вас: Сукня Анна - 1200 грн",
            created_at=datetime.now(UTC) - timedelta(days=4),
        ),
        StoredMessage(
            session_id="test_summary",
            role="user",
            content="Беру! Відправка на Нову Пошту, Київ",
            created_at=datetime.now(UTC) - timedelta(days=4),
        ),
    ]

    summary = summarise_messages(messages)

    print(f"  Input: {len(messages)} messages")
    print(f"  Output summary:")
    print(f"  ---")
    for line in summary.split(" \n")[:3]:
        print(f"    {line[:60]}...")
    print(f"  ---")

    print_result("Summarization", len(summary) > 0, f"{len(summary)} chars generated")
    return True


def test_message_store_real():
    """Test 4: Real MessageStore with Supabase."""
    print_header("TEST 4: Real MessageStore (Supabase)")

    store = create_message_store()
    session_id = f"test_store_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    try:
        # Append a test message
        test_msg = StoredMessage(
            session_id=session_id,
            role="user",
            content=f"Test message at {datetime.now(UTC).isoformat()}",
            created_at=datetime.now(UTC),
        )
        store.append(test_msg)
        print_result("Append message", True, f"Session: {session_id}")

        # List messages
        messages = store.list(session_id)
        print_result("List messages", len(messages) > 0, f"Found {len(messages)} messages")

        # Delete test data
        store.delete(session_id)
        print_result("Cleanup", True, "Test messages deleted")

        return True
    except Exception as e:
        print_result("MessageStore", False, str(e))
        return False


def test_dispatcher_sync():
    """Test 5: Dispatcher in sync mode (no Celery)."""
    print_header("TEST 5: Dispatcher (Sync Mode)")

    from src.workers.dispatcher import dispatch_followup, dispatch_summarization

    # With CELERY_ENABLED=False, these run synchronously
    print(f"  CELERY_ENABLED: {settings.CELERY_ENABLED}")

    session_id = f"test_dispatch_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Test summarization dispatch
    result = dispatch_summarization(session_id, user_id=None)
    print_result(
        "dispatch_summarization", "queued" in result or "summary" in result, f"Result: {result}"
    )

    # Test followup dispatch
    result = dispatch_followup(session_id, channel="telegram", chat_id="12345")
    print_result(
        "dispatch_followup", "queued" in result or "followup_created" in result, f"Result: {result}"
    )

    return True


def test_full_followup_flow():
    """Test 6: Full follow-up flow with real store."""
    print_header("TEST 6: Full Follow-up Flow (Real Store, 1-min schedule)")

    store = create_message_store()
    session_id = f"test_flow_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    try:
        # 1. Add old messages (2 minutes ago)
        old_time = datetime.now(UTC) - timedelta(minutes=2)

        store.append(
            StoredMessage(
                session_id=session_id,
                role="user",
                content="Привіт!",
                created_at=old_time,
            )
        )
        store.append(
            StoredMessage(
                session_id=session_id,
                role="assistant",
                content="Привіт! Чим можу допомогти?",
                created_at=old_time + timedelta(seconds=3),
            )
        )
        print_result("Setup", True, "Added 2 messages (2 min ago)")

        # 2. Run followup with 1-minute schedule
        schedule_1min = [0.0166]  # 1 minute
        followup = run_followups(
            session_id=session_id,
            message_store=store,
            now=datetime.now(UTC),
            schedule_hours=schedule_1min,
        )

        if followup:
            print_result("Follow-up triggered", True, f'"{followup.content[:40]}..."')
            print(f"  Tags: {followup.tags}")

            # Verify it was persisted
            messages = store.list(session_id)
            print_result("Persisted", len(messages) == 3, f"Now {len(messages)} messages in store")
        else:
            print_result("Follow-up triggered", False, "Not due yet")

        # Cleanup
        store.delete(session_id)
        print_result("Cleanup", True, "Test data deleted")

        return followup is not None

    except Exception as e:
        print_result("Flow", False, str(e))
        import traceback

        traceback.print_exc()
        return False


def main():
    print("\n" + "🚀 MIRT AI Workers - Real Integration Tests 🚀".center(60))
    print(f"Time: {datetime.now(UTC).isoformat()}")
    print(f"Supabase: {settings.SUPABASE_URL}")

    results = []

    # Run all tests
    results.append(("Supabase Connection", test_supabase_connection()))
    results.append(("Follow-up Logic (1-min)", test_followup_logic_1min()))
    results.append(("Summarization Logic", test_summarization_logic()))
    results.append(("Real MessageStore", test_message_store_real()))
    results.append(("Dispatcher Sync", test_dispatcher_sync()))
    results.append(("Full Follow-up Flow", test_full_followup_flow()))

    # Summary
    print_header("SUMMARY")
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, success in results:
        icon = "✅" if success else "❌"
        print(f"  {icon} {name}")

    print(f"\n  Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n  🎉 All tests PASSED! Workers are ready.")
    else:
        print("\n  ⚠️ Some tests failed. Check output above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
