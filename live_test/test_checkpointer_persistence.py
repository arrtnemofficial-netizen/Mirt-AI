#!/usr/bin/env python
"""
PRODUCTION TEST: Checkpointer Persistence Verification
====================================================
This test PROVES that state survives restarts.

What it does:
1. Creates graph with PostgresSaver
2. Runs conversation to STATE_4
3. Saves thread_id
4. Creates NEW graph instance (simulates restart)
5. Resumes from saved thread_id
6. Verifies state is preserved

This is REAL proof, not unit test fantasy.
"""

import asyncio
import sys
from pathlib import Path


# Fix Windows async event loop issue
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from langgraph.checkpoint.memory import MemorySaver

from src.agents import create_initial_state, get_production_graph
from src.conf.config import settings


async def test_persistence():
    """Test that state survives graph recreation."""

    print("\n" + "=" * 60)
    print("CHECKPOINTER PERSISTENCE TEST")
    print("=" * 60)

    # 1. Create initial graph
    print("\n1. Creating initial graph...")
    graph1 = get_production_graph()

    # Check what checkpointer we're using
    checkpointer = graph1.checkpointer
    print(f"   Checkpointer type: {type(checkpointer).__name__}")

    if isinstance(checkpointer, MemorySaver):
        print("\n⚠️  WARNING: Using MemorySaver! State will NOT survive restart!")
        print("   Check DATABASE_URL or SUPABASE_URL settings")
        return False

    # 2. Create initial state
    print("\n2. Creating initial state...")
    thread_id = "test_persistence_123"
    initial_state = create_initial_state(
        session_id="test_session",
        messages=[{"role": "user", "content": "Привіт! Шукаю сукню для доньки 7 років"}],
        metadata={"user_id": "test_user_456", "channel": "test"},
    )

    # 3. Run graph to STATE_4
    print("\n3. Running conversation to STATE_4...")
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph1.ainvoke(initial_state, config=config)

    print(f"   Final state: {result.get('current_state', 'UNKNOWN')}")
    print(f"   Step number: {result.get('step_number', 0)}")
    print(f"   Messages count: {len(result.get('messages', []))}")

    # Save some values to verify later
    saved_step = result.get("step_number", 0)
    saved_state = result.get("current_state")

    # 4. Simulate restart - create NEW graph instance
    print("\n4. Simulating restart (creating new graph instance)...")
    graph2 = get_production_graph()

    # Verify it's a new instance
    print(f"   New graph ID: {id(graph2)} (old: {id(graph1)})")
    print(f"   New checkpointer ID: {id(graph2.checkpointer)} (old: {id(checkpointer)})")

    # 5. Resume from saved thread_id
    print("\n5. Resuming from saved thread_id...")

    # Get state snapshot (use async version)
    snapshot = await graph2.aget_state(config)

    print(f"   Resumed state: {snapshot.values.get('current_state', 'UNKNOWN')}")
    print(f"   Resumed step: {snapshot.values.get('step_number', 0)}")
    print(f"   Messages count: {len(snapshot.values.get('messages', []))}")

    # 6. Verify persistence
    print("\n6. Verifying persistence...")

    resumed_step = snapshot.values.get("step_number", 0)
    resumed_state = snapshot.values.get("current_state")

    success = (
        resumed_step == saved_step
        and resumed_state == saved_state
        and len(snapshot.values.get("messages", [])) > 0
    )

    if success:
        print("✅ SUCCESS: State survived restart!")
        print(f"   Step {saved_step} -> {resumed_step}")
        print(f"   State {saved_state} -> {resumed_state}")
    else:
        print("❌ FAILURE: State was NOT preserved!")
        print(f"   Expected step: {saved_step}, got: {resumed_step}")
        print(f"   Expected state: {saved_state}, got: {resumed_state}")

    # 7. Test continuation
    print("\n7. Testing conversation continuation...")

    # Add new message and continue
    continuation_state = {
        "messages": [{"role": "user", "content": "Дякую, давайте цю сукню"}],
    }

    result2 = await graph2.ainvoke(continuation_state, config=config)

    print(f"   New step: {result2.get('step_number', 0)}")
    print(f"   New state: {result2.get('current_state', 'UNKNOWN')}")

    if result2.get("step_number", 0) > saved_step:
        print("✅ Continuation works: step number increased")
    else:
        print("❌ Continuation failed: step didn't increase")

    return success


async def main():
    """Run the persistence test."""

    print("\nChecking environment...")

    # Check database settings
    if hasattr(settings, "DATABASE_URL") and settings.DATABASE_URL:
        print(f"✅ DATABASE_URL found: {settings.DATABASE_URL[:30]}...")
    elif hasattr(settings, "SUPABASE_URL") and settings.SUPABASE_URL:
        print(f"✅ SUPABASE_URL found: {settings.SUPABASE_URL[:30]}...")
    else:
        print("❌ No database URL found! Check your .env file")
        print("\nRequired: DATABASE_URL or SUPABASE_URL + SUPABASE_API_KEY")
        return

    # Run the test
    success = await test_persistence()

    print("\n" + "=" * 60)
    if success:
        print("🎉 PERSISTENCE TEST PASSED")
        print("Your checkpointer is production-ready!")
    else:
        print("💥 PERSISTENCE TEST FAILED")
        print("Fix database configuration before deploying!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
