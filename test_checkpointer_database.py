#!/usr/bin/env python
"""
DATABASE-LEVEL CHECKPOINTER VERIFICATION
=========================================
This is the REAL proof - we query Supabase directly
to verify that checkpoints are actually saved.

No async issues, no Windows problems - just raw SQL.
"""

import sys
from pathlib import Path


# Add project root
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

import asyncio

from src.agents import create_initial_state, get_production_graph
from src.services.supabase import get_supabase_client


async def test_database_persistence():
    """Test that checkpoints are saved to Supabase."""

    print("\n" + "=" * 60)
    print("DATABASE-LEVEL PERSISTENCE TEST")
    print("=" * 60)

    # 1. Get Supabase client
    print("\n1. Connecting to Supabase...")
    client = get_supabase_client()

    if not client:
        print("❌ Failed to connect to Supabase")
        return False

    print("✅ Connected to Supabase")

    # 2. Check if checkpoints table exists
    print("\n2. Checking checkpoints table...")

    try:
        # Try to query the table structure
        result = client.rpc("get_table_columns", {"table_name": "checkpoints"}).execute()
        if result.data:
            print("✅ Checkpoints table exists")
        else:
            # Try alternative approach
            result = client.table("checkpoints").select("count", count="exact").execute()
            print(f"✅ Checkpoints table exists (rows: {result.count})")
    except Exception as e:
        print(f"❌ Checkpoints table error: {e}")
        print("\nThis means LangGraph hasn't created the table yet.")
        print("The table is created on first use.")
        return False

    # 3. Clear old test data
    print("\n3. Cleaning old test data...")
    thread_id = "test_db_persistence_456"

    try:
        client.table("checkpoints").delete().eq("thread_id", thread_id).execute()
        print("✅ Old test data cleared")
    except Exception as e:
        print(f"⚠️  Could not clear old data: {e}")

    # 4. Run a conversation to create checkpoints
    print("\n4. Running conversation to create checkpoints...")

    graph = get_production_graph()
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = create_initial_state(
        session_id="test_session",
        messages=[{"role": "user", "content": "Привіт! Потрібна сукня для доньки 8 років"}],
        metadata={"user_id": "test_user_789", "channel": "test"},
    )

    # Run just a few steps
    result = await graph.ainvoke(initial_state, config=config)

    print(f"   Final state: {result.get('current_state', 'UNKNOWN')}")
    print(f"   Step number: {result.get('step_number', 0)}")

    # 5. Query database directly
    print("\n5. Querying database for checkpoints...")

    try:
        # Get all checkpoints for our thread
        result = client.table("checkpoints").select("*").eq("thread_id", thread_id).execute()

        checkpoints = result.data
        print(f"   Found {len(checkpoints)} checkpoints")

        if checkpoints:
            # Show first checkpoint details
            cp = checkpoints[0]
            print("\n   First checkpoint:")
            print(f"   - ID: {cp.get('id', 'N/A')}")
            print(f"   - Thread ID: {cp.get('thread_id', 'N/A')}")
            print(f"   - Checkpoint ID: {cp.get('checkpoint_id', 'N/A')}")
            print(f"   - Created: {cp.get('created_at', 'N/A')}")

            # Verify state is saved
            if cp.get("checkpoint_data"):
                import json

                data = json.loads(cp["checkpoint_data"])
                channel_values = data.get("channel_values", {})
                step = channel_values.get("step_number", 0)
                print(f"   - Saved step: {step}")

                if step > 0:
                    print("\n✅ SUCCESS: Checkpoint data contains valid state!")
                else:
                    print("\n⚠️  Checkpoint saved but step number is 0")
            else:
                print("\n❌ No checkpoint_data found")
        else:
            print("\n❌ No checkpoints found in database!")
            return False

    except Exception as e:
        print(f"\n❌ Database query failed: {e}")
        return False

    # 6. Test state recovery
    print("\n6. Testing state recovery...")

    # Create new graph instance
    graph2 = get_production_graph()

    # Get state from database
    try:
        snapshot = await graph2.aget_state(config)
        recovered_step = snapshot.values.get("step_number", 0)

        print(f"   Recovered step: {recovered_step}")

        if recovered_step == result.get("step_number", 0):
            print("✅ State recovered correctly!")
            return True
        else:
            print(f"❌ State mismatch: expected {result.get('step_number')}, got {recovered_step}")
            return False

    except Exception as e:
        print(f"❌ Recovery failed: {e}")
        return False


async def main():
    """Run the database persistence test."""

    # Check environment
    print("\nChecking Supabase configuration...")

    from src.conf.config import settings

    if hasattr(settings, "SUPABASE_URL") and settings.SUPABASE_URL:
        print(f"✅ SUPABASE_URL: {settings.SUPABASE_URL[:50]}...")
    else:
        print("❌ No SUPABASE_URL found")
        return

    if hasattr(settings, "SUPABASE_API_KEY") and settings.SUPABASE_API_KEY:
        print(f"✅ SUPABASE_API_KEY: {'*' * 20}{settings.SUPABASE_API_KEY.get_secret_value()[-4:]}")
    else:
        print("❌ No SUPABASE_API_KEY found")
        return

    # Run the test
    success = await test_database_persistence()

    print("\n" + "=" * 60)
    if success:
        print("🎉 DATABASE PERSISTENCE VERIFIED!")
        print("Checkpoints are saved to Supabase and survive restarts.")
    else:
        print("💥 PERSISTENCE TEST FAILED!")
        print("Check your database configuration.")
    print("=" * 60)


if __name__ == "__main__":
    # Fix Windows event loop
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
