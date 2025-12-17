#!/usr/bin/env python3
"""Test full ManyChat flow with Celery."""

import sys
import time

# Add project root to path
sys.path.append('.')

from src.workers.tasks.manychat import process_manychat_message


def test_celery_task():
    """Test Celery task execution."""
    print("=== Testing Celery ManyChat Task ===")
    
    # Test data
    user_id = "test_user_456"
    text = "Hello from test"
    channel = "instagram"
    subscriber_data = {
        "name": "Test User",
        "instagram_username": "testuser"
    }
    
    # Run task synchronously (without actual Celery broker)
    result = process_manychat_message(
        user_id=user_id,
        text=text,
        channel=channel,
        subscriber_data=subscriber_data
    )
    
    print(f"Task result: {result}")
    
    if result.get("status") == "success":
        print("✅ Celery task works!")
    else:
        print("❌ Task failed:", result.get("error"))


if __name__ == "__main__":
    test_celery_task()
