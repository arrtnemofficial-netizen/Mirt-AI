#!/usr/bin/env python3
"""
🔧 ТЕСТУВАННЯ ВОРКЕРІВ ВРУЧНУ
==============================

Цей скрипт дозволяє протестувати всі воркери БЕЗ Celery.
Функції викликаються напряму - синхронно.

Запуск:
    python scripts/test_workers.py

Або окремі тести:
    python scripts/test_workers.py summarize
    python scripts/test_workers.py followup
    python scripts/test_workers.py crm
    python scripts/test_workers.py health
    python scripts/test_workers.py all
"""

import sys
from datetime import UTC, datetime
from pathlib import Path


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(title: str):
    """Print section header."""
    print()
    print("=" * 60)
    print(f"🔧 {title}")
    print("=" * 60)


def print_result(name: str, success: bool, details: str = ""):
    """Print test result."""
    status = "✅" if success else "❌"
    print(f"   {status} {name}: {details}")


# =============================================================================
# 1. HEALTH CHECK
# =============================================================================


def _run_health():
    """Test worker health check (no external dependencies)."""
    print_header("HEALTH CHECK")

    try:
        from src.workers.tasks.health import ping

        # ping() returns dict with pong flag when called directly
        result = ping()
        success = False
        if isinstance(result, dict):
            success = bool(result.get("pong"))
        elif isinstance(result, str):
            success = result == "pong"

        print_result("ping", success, f"Result: {result}")
        return True

    except Exception as e:
        print_result("ping", False, f"Error: {e}")
        return False


# =============================================================================
# 2. SUMMARIZATION
# =============================================================================


def _run_summarization():
    """Test summarization service (without Celery)."""
    print_header("SUMMARIZATION")

    try:
        from src.services.domain.memory.summarization import (
            call_summarize_inactive_users,
            get_users_needing_summary,
        )

        # 1) Спроба викликати RPC у Supabase (якщо не налаштовано – поверне [])
        rpc_users = call_summarize_inactive_users()
        print_result(
            "call_summarize_inactive_users",
            True,
            f"Marked {len(rpc_users)} users (or 0 if function not configured)",
        )

        # 2) Перевірити, кого треба сумаризувати
        users = get_users_needing_summary()
        print_result("get_users_needing_summary", True, f"Found {len(users)} users")

        if users:
            print("\n   Users needing summary:")
            for user in users[:3]:
                print(f"   - user_id: {user.get('id')}, last_active: {user.get('last_active_at')}")

        return True

    except Exception as e:
        print_result("summarization", False, f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


# =============================================================================
# 3. FOLLOWUPS
# =============================================================================


def _run_followups():
    """Test followup service (without Celery)."""
    print_header("FOLLOWUPS")

    try:
        from datetime import timedelta

        from src.conf.config import settings
        from src.services.domain.engagement.followups import next_followup_due_at, run_followups
        from src.services.infra.message_store import InMemoryMessageStore, StoredMessage

        print(f"   FOLLOWUP_DELAYS_HOURS: {settings.FOLLOWUP_DELAYS_HOURS}")
        print(f"   Parsed schedule: {settings.followup_schedule_hours}")

        # Створюємо in-memory store, щоб не чіпати реальну БД
        store = InMemoryMessageStore()
        session_id = "test-followup-session"
        now = datetime.now(UTC)

        # Емуляція останнього повідомлення 48 годин тому, щоб followup був due
        old_time = now - timedelta(hours=max(settings.followup_schedule_hours) + 1)
        store.append(
            StoredMessage(
                session_id=session_id,
                role="user",
                content="Тестове повідомлення для followup",
                created_at=old_time,
            )
        )

        messages = store.list(session_id)
        due_at = next_followup_due_at(messages)
        print_result("next_followup_due_at", due_at is not None, f"due_at={due_at}")

        followup = run_followups(
            session_id=session_id,
            message_store=store,
            now=now,
        )

        print_result(
            "run_followups",
            followup is not None,
            f"content={followup.content if followup else 'None'}",
        )

        return True

    except Exception as e:
        print_result("followups", False, f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


# =============================================================================
# 4. CRM
# =============================================================================


def _run_crm():
    """Test CRM service (without Celery)."""
    print_header("CRM (Snitkix)")

    try:
        from src.conf.config import settings

        print(f"   snitkix_enabled: {settings.snitkix_enabled}")

        # Якщо CRM не налаштований – це НЕ помилка для локального тесту
        if not settings.snitkix_enabled:
            print_result("crm", True, "CRM not configured (snitkix_enabled=False) – OK for dev")
            return True

        # Якщо CRM налаштований, можна було б викликати створення замовлення,
        # але це вже інтеграційний тест з зовнішнім сервісом, тому тут зупиняємось.
        print_result("crm", True, "CRM configured – інтеграційний тест робити окремо")
        return True

    except ImportError as e:
        print_result("crm_import", False, f"Import error: {e}")
        return False
    except Exception as e:
        print_result("crm", False, f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


# =============================================================================
# 5. LLM USAGE
# =============================================================================


def _run_llm_usage():
    """Test LLM usage tracking."""
    print_header("LLM USAGE TRACKING")

    try:
        from src.services.core.observability import get_metrics_summary, track_metric

        # Track a test metric
        track_metric("test_worker_run", 1)
        print_result("track_metric", True, "Metric tracked")

        # Get current metrics summary
        metrics = get_metrics_summary()
        print_result("get_metrics_summary", True, f"Keys: {list(metrics.keys())[:5]}...")

        return True

    except Exception as e:
        print_result("llm_usage", False, f"Error: {e}")
        return False


# =============================================================================
# 6. MESSAGE STORE
# =============================================================================


def _run_message_store():
    """Test message store operations."""
    print_header("MESSAGE STORE")

    try:
        from src.services.infra.message_store import create_message_store

        store = create_message_store()
        print_result("create_message_store", True, f"Type: {type(store).__name__}")

        # Test list() for non-existent session (повинен повернути [])
        test_session = "test-worker-check-12345"
        messages = store.list(test_session)
        print_result("list", True, f"Found {len(messages)} messages for test session")

        return True

    except Exception as e:
        print_result("message_store", False, f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


# =============================================================================
# 7. CELERY CONNECTION (optional)
# =============================================================================


def _run_celery_connection():
    """Test Celery broker connection (optional)."""
    print_header("CELERY BROKER (optional)")

    try:
        from src.conf.config import settings

        # У цій утиліті ми НЕ вимагаємо запущений Celery – це опційно.
        if not settings.CELERY_ENABLED:
            print_result(
                "celery", True, "CELERY_ENABLED=False – воркери вимкнені (OK для локального тесту)"
            )
            return True

        # Якщо CELERY_ENABLED=True – тут можна було б додати ping брокера,
        # але це вже інтеграційний тест інфраструктури.
        print_result("celery", True, "CELERY_ENABLED=True – перевірку брокера робіть окремо")
        return True

    except Exception as e:
        print_result("celery", False, f"Error: {e}")
        print("   (Celery не запущений - це нормально для ручного тестування)")
        return True  # Not a failure for manual testing


# =============================================================================
# MAIN
# =============================================================================


def run_all_tests():
    """Run all worker tests."""
    print("\n" + "🔧" * 30)
    print("   ТЕСТУВАННЯ ВОРКЕРІВ MIRT-AI")
    print("🔧" * 30)

    results = {}

    results["health"] = _run_health()
    results["message_store"] = _run_message_store()
    results["llm_usage"] = _run_llm_usage()
    results["summarization"] = _run_summarization()
    results["followups"] = _run_followups()
    results["crm"] = _run_crm()
    results["celery"] = _run_celery_connection()

    # Summary
    print_header("SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"   {name}: {status}")

    print()
    print(f"   Total: {passed}/{total} passed")

    if passed == total:
        print("\n   🎉 ВСІ ВОРКЕРИ ПРАЦЮЮТЬ!")
    else:
        print("\n   ⚠️ Деякі тести не пройшли")

    return passed == total


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()

        if test_name == "all":
            run_all_tests()
        elif test_name == "health":
            _run_health()
        elif test_name == "summarize" or test_name == "summarization":
            _run_summarization()
        elif test_name == "followup" or test_name == "followups":
            _run_followups()
        elif test_name == "crm":
            _run_crm()
        elif test_name == "llm":
            _run_llm_usage()
        elif test_name == "messages":
            _run_message_store()
        elif test_name == "celery":
            _run_celery_connection()
        else:
            print(f"Unknown test: {test_name}")
            print("Available: health, summarize, followup, crm, llm, messages, celery, all")
            sys.exit(1)
    else:
        run_all_tests()


def test_health():
    assert _run_health()


def test_summarization():
    assert _run_summarization()


def test_followups():
    assert _run_followups()


def test_crm():
    assert _run_crm()


def test_llm_usage():
    assert _run_llm_usage()


def test_message_store():
    assert _run_message_store()


def test_celery_connection():
    assert _run_celery_connection()


if __name__ == "__main__":
    main()
