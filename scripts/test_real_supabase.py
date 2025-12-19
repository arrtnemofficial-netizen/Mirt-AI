#!/usr/bin/env python
"""Test with REAL Supabase tables (mirt_messages, mirt_users)."""

import sys
from datetime import UTC, datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent / ".env")

from src.services.supabase_client import get_supabase_client


def main():
    client = get_supabase_client()
    if not client:
        print("❌ No Supabase client!")
        return False

    print("=" * 60)
    print("  REAL SUPABASE TEST (mirt_messages, mirt_users)")
    print("=" * 60)

    # 1. Read existing messages from mirt_messages
    print("\n📥 1. Reading mirt_messages:")
    try:
        r = client.table("mirt_messages").select("*").limit(5).execute()
        print(f"   Found {len(r.data)} messages")
        for row in r.data[:3]:
            sid = row.get("session_id", "?")
            role = row.get("role", "?")
            content = str(row.get("content", ""))[:40]
            print(f"   • session={sid}, role={role}, content='{content}...'")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # 2. Read existing users from mirt_users
    print("\n📥 2. Reading mirt_users:")
    try:
        r = client.table("mirt_users").select("*").limit(3).execute()
        print(f"   Found {len(r.data)} users")
        for row in r.data[:3]:
            uid = row.get("user_id", "?")
            summary = str(row.get("summary", ""))[:40] if row.get("summary") else "None"
            print(f"   • user_id={uid}, summary='{summary}...'")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 3. Write test message
    print("\n📤 3. Writing test message to mirt_messages:")
    test_session = f"test_real_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    try:
        payload = {
            "session_id": test_session,
            "role": "user",
            "content": "🧪 REAL TEST: Integration test message from Cascade",
            "content_type": "text",
            "created_at": datetime.now(UTC).isoformat(),
        }
        client.table("mirt_messages").insert(payload).execute()
        print(f"   ✅ Inserted: session={test_session}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # 4. Read it back
    print("\n📥 4. Reading back:")
    try:
        r = client.table("mirt_messages").select("*").eq("session_id", test_session).execute()
        print(f"   Found {len(r.data)} messages")
        if r.data:
            print(f"   Content: {r.data[0].get('content')}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # 5. Test follow-up flow with real store
    print("\n🔄 5. Testing follow-up with REAL mirt_messages:")
    try:
        from src.services.followups import (
            build_followup_message,
            next_followup_due_at,
        )
        from src.services.message_store import StoredMessage

        # Create old message (2 min ago)
        old_time = datetime.now(UTC) - timedelta(minutes=2)

        messages = [
            StoredMessage(
                session_id=test_session,
                role="user",
                content="Тест follow-up",
                created_at=old_time,
            ),
        ]

        # Check with 1-minute schedule
        schedule_1min = [0.0166]  # 1 minute
        due_at = next_followup_due_at(messages, schedule_hours=schedule_1min)
        now = datetime.now(UTC)

        print(f"   Last activity: {messages[-1].created_at.isoformat()}")
        print(f"   Current time:  {now.isoformat()}")
        print(f"   Due at:        {due_at.isoformat() if due_at else 'None'}")

        if due_at and now >= due_at:
            followup = build_followup_message(test_session, index=1, now=now)
            print(f"   ✅ Follow-up triggered: '{followup.content[:40]}...'")
        else:
            print("   ❌ Follow-up not triggered")

    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback

        traceback.print_exc()

    # 6. Cleanup
    print("\n🧹 6. Cleanup:")
    try:
        client.table("mirt_messages").delete().eq("session_id", test_session).execute()
        print(f"   ✅ Deleted test session {test_session}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n" + "=" * 60)
    print("  ✅ REAL SUPABASE TEST COMPLETED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    from datetime import timedelta

    success = main()
    sys.exit(0 if success else 1)
