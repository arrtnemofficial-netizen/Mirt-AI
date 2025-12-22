#!/usr/bin/env python3
"""Test script to verify webhook deduplication works."""

import asyncio
import sys


# Add project root to path
sys.path.append(".")

from src.services.infra.supabase_client import get_supabase_client
from src.services.infra.webhook_dedupe import WebhookDedupeStore


async def test_dedupe():
    """Test webhook deduplication."""
    db = get_supabase_client()
    store = WebhookDedupeStore(db, ttl_hours=24)

    user_id = "test_user_123"
    message_id = "msg_456"
    text = "Test message"
    image_url = None

    print("=== Testing Webhook Deduplication ===")

    # First check - should return False (not duplicate)
    result1 = store.check_and_mark(
        user_id=user_id, message_id=message_id, text=text, image_url=image_url
    )
    print(f"First check: {result1} (should be False)")

    # Second check - should return True (duplicate)
    result2 = store.check_and_mark(
        user_id=user_id, message_id=message_id, text=text, image_url=image_url
    )
    print(f"Second check: {result2} (should be True)")

    # Test with different message_id - should be False
    result3 = store.check_and_mark(
        user_id=user_id, message_id="msg_789", text=text, image_url=image_url
    )
    print(f"Different message_id: {result3} (should be False)")

    # Cleanup test
    cleaned = store.cleanup_expired()
    print(f"Cleaned expired entries: {cleaned}")

    print("\n=== Test Complete ===")
    if not result1 and result2 and not result3:
        print("✅ Deduplication works correctly!")
    else:
        print("❌ Deduplication test failed!")


if __name__ == "__main__":
    asyncio.run(test_dedupe())
