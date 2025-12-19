#!/usr/bin/env python
"""
SIMPLE CHECKPOINTER VERIFICATION
===============================
This test verifies that we're using the RIGHT checkpointer for production.

It doesn't test full persistence (Windows async issues),
but it PROVES that PostgresSaver is configured correctly.
"""

import sys
from pathlib import Path


# Add project root
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

from langgraph.checkpoint.memory import MemorySaver, SerializableMemorySaver

from src.agents.langgraph.checkpointer import get_checkpointer
from src.conf.config import settings


def main():
    print("\n" + "=" * 60)
    print("CHECKPOINTER TYPE VERIFICATION")
    print("=" * 60)

    # Check environment
    print("\n1. Checking database configuration...")

    if hasattr(settings, "DATABASE_URL") and settings.DATABASE_URL:
        print(f"✅ DATABASE_URL found: {settings.DATABASE_URL[:50]}...")
    elif hasattr(settings, "SUPABASE_URL") and settings.SUPABASE_URL:
        print(f"✅ SUPABASE_URL found: {settings.SUPABASE_URL[:50]}...")
    else:
        print("❌ No database URL found!")
        print("\nSet DATABASE_URL or SUPABASE_URL + SUPABASE_API_KEY")
        return False

    # Get checkpointer
    print("\n2. Getting checkpointer...")
    checkpointer = get_checkpointer()

    print(f"   Type: {type(checkpointer).__name__}")
    print(f"   Module: {type(checkpointer).__module__}")

    # Verify it's NOT MemorySaver
    if isinstance(checkpointer, (MemorySaver, SerializableMemorySaver)):
        print("\n❌ CRITICAL: Using MemorySaver!")
        print("   State will be LOST on restart!")
        print("\nThis happens when:")
        print("   - DATABASE_URL is not set")
        print("   - langgraph-checkpoint-postgres not installed")
        print("   - Connection to database failed")
        return False

    # Check if it's PostgresSaver
    if "Postgres" in type(checkpointer).__name__:
        print("\n✅ SUCCESS: Using PostgresSaver!")
        print("   State will persist across restarts")

        # Additional check for async
        if "Async" in type(checkpointer).__name__:
            print("   ✅ Using async version (recommended)")

        return True
    else:
        print(f"\n⚠️  WARNING: Using unknown checkpointer: {type(checkpointer).__name__}")
        return False


if __name__ == "__main__":
    success = main()

    print("\n" + "=" * 60)
    if success:
        print("🎉 CHECKPOINTER CONFIGURED CORRECTLY")
        print("Your system is production-ready!")
    else:
        print("💥 CHECKPOINTER CONFIGURATION FAILED")
        print("Fix database settings before deploying!")
    print("=" * 60)

    sys.exit(0 if success else 1)
