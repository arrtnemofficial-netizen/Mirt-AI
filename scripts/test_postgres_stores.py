#!/usr/bin/env python3
"""Test PostgreSQL stores."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.postgres_pool import get_postgres_pool, health_check
from src.services.postgres_store import PostgresSessionStore
from src.services.postgres_message_store import PostgresMessageStore
from src.services.message_store import StoredMessage
from datetime import UTC, datetime


async def test_pool():
    """Test connection pool."""
    print("Testing PostgreSQL connection pool...")
    try:
        pool = await get_postgres_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()
                print(f"✅ Pool connection works: {result}")
        return True
    except Exception as e:
        print(f"❌ Pool connection failed: {e}")
        return False


async def test_session_store():
    """Test PostgresSessionStore."""
    print("\nTesting PostgresSessionStore...")
    try:
        store = PostgresSessionStore()
        
        # Test save
        from src.agents import ConversationState
        from src.core.constants import AgentState as StateEnum
        
        test_session_id = "test_postgres_session_123"
        state = ConversationState(
            messages=[],
            metadata={"session_id": test_session_id, "test": True},
            current_state=StateEnum.default(),
        )
        
        store.save(test_session_id, state)
        print("✅ Save works")
        
        # Test get
        retrieved = store.get(test_session_id)
        if retrieved and retrieved.get("metadata", {}).get("test"):
            print("✅ Get works")
        else:
            print("❌ Get failed - state not retrieved correctly")
            return False
        
        # Test delete
        deleted = store.delete(test_session_id)
        if deleted:
            print("✅ Delete works")
        else:
            print("⚠️  Delete returned False (session may not have existed)")
        
        return True
    except Exception as e:
        print(f"❌ SessionStore test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_message_store():
    """Test PostgresMessageStore."""
    print("\nTesting PostgresMessageStore...")
    try:
        store = PostgresMessageStore()
        
        test_session_id = "test_postgres_messages_123"
        msg = StoredMessage(
            session_id=test_session_id,
            role="user",
            content="Test message",
            created_at=datetime.now(UTC),
        )
        
        # Test append
        store.append(msg)
        print("✅ Append works")
        
        # Test list
        messages = store.list(test_session_id)
        if len(messages) > 0:
            print(f"✅ List works: {len(messages)} messages")
        else:
            print("❌ List failed - no messages retrieved")
            return False
        
        # Test delete
        store.delete(test_session_id)
        messages_after = store.list(test_session_id)
        if len(messages_after) == 0:
            print("✅ Delete works")
        else:
            print(f"⚠️  Delete may have failed: {len(messages_after)} messages remain")
        
        return True
    except Exception as e:
        print(f"❌ MessageStore test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("PostgreSQL Stores Test")
    print("=" * 60)
    print()
    
    # Test health check
    print("Testing health check...")
    healthy = await health_check()
    if healthy:
        print("✅ Health check passed")
    else:
        print("❌ Health check failed")
        return
    
    # Test pool
    pool_ok = await test_pool()
    if not pool_ok:
        return
    
    # Test session store
    session_ok = await test_session_store()
    
    # Test message store
    message_ok = await test_message_store()
    
    print()
    print("=" * 60)
    if pool_ok and session_ok and message_ok:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("=" * 60)


if __name__ == "__main__":
    # Use SelectorEventLoop on Windows for psycopg compatibility
    import sys
    if sys.platform == "win32":
        import selectors
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    else:
        asyncio.run(main())

