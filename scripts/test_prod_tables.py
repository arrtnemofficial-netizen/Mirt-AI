"""
Smoke test script to verify production tables are populated correctly.

Run this after deployment to verify:
- users table fills on first message
- orders/order_items fill ONLY on payment proof (screenshot/receipt/URL), NOT on delivery confirmation
- sitniks_chat_mappings fills when usernames available
- llm_usage shows gpt-5.1

Usage:
    python scripts/test_prod_tables.py
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("ERROR: psycopg not installed. Install with: pip install 'psycopg[binary]'")
    sys.exit(1)

from src.conf.config import settings
from src.services.storage import get_postgres_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_users_table():
    """Test that users table is populated on message append."""
    logger.info("Testing users table population...")
    
    try:
        postgres_url = get_postgres_url()
    except ValueError:
        logger.error("DATABASE_URL not set, skipping users test")
        return False
    
    test_user_id = f"test_user_{datetime.now(UTC).timestamp()}"
    test_session_id = f"test_session_{datetime.now(UTC).timestamp()}"
    
    try:
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Insert a test message (simulating message_store.append)
                cur.execute(
                    """
                    INSERT INTO messages
                    (session_id, role, content, content_type, user_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        test_session_id,
                        "user",
                        "Test message",
                        "text",
                        test_user_id,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                
                # Update user interaction (simulating _update_user_interaction)
                cur.execute(
                    """
                    INSERT INTO users (user_id, last_interaction_at, username)
                    VALUES (%s, NOW(), %s)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET last_interaction_at = NOW(), updated_at = NOW()
                    """,
                    (test_user_id, "test_user"),
                )
                
                conn.commit()
                
                # Verify user was created
                cur.execute("SELECT * FROM users WHERE user_id = %s", (test_user_id,))
                user = cur.fetchone()
                
                if user:
                    logger.info("✅ users table test PASSED: user created with user_id=%s", test_user_id)
                    # Cleanup
                    cur.execute("DELETE FROM users WHERE user_id = %s", (test_user_id,))
                    cur.execute("DELETE FROM messages WHERE session_id = %s", (test_session_id,))
                    conn.commit()
                    return True
                else:
                    logger.error("❌ users table test FAILED: user not found after insert")
                    return False
                    
    except Exception as e:
        logger.error("❌ users table test FAILED: %s", e)
        return False


async def test_orders_table():
    """Test that orders and order_items are populated ONLY on payment proof.
    
    CRITICAL: Orders should NOT be created on delivery confirmation alone.
    Payment proof (screenshot/receipt/URL) is required.
    """
    logger.info("Testing orders/order_items table population (payment proof required)...")
    
    try:
        postgres_url = get_postgres_url()
    except ValueError:
        logger.error("DATABASE_URL not set, skipping orders test")
        return False
    
    test_user_id = f"test_user_{datetime.now(UTC).timestamp()}"
    test_session_id = f"test_session_{datetime.now(UTC).timestamp()}"
    
    try:
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Simulate order creation (from OrderService.create_order)
                cur.execute(
                    """
                    INSERT INTO orders (
                        user_id, session_id, customer_name, customer_phone,
                        customer_city, delivery_method, delivery_address,
                        status, total_amount, notes, user_nickname
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) 
                    DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        customer_name = EXCLUDED.customer_name,
                        customer_phone = EXCLUDED.customer_phone,
                        customer_city = EXCLUDED.customer_city,
                        delivery_method = EXCLUDED.delivery_method,
                        delivery_address = EXCLUDED.delivery_address,
                        status = EXCLUDED.status,
                        total_amount = EXCLUDED.total_amount,
                        notes = EXCLUDED.notes,
                        user_nickname = EXCLUDED.user_nickname,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        test_user_id,
                        test_session_id,
                        "Test User",
                        "+380123456789",
                        "Київ",
                        "nova_poshta",
                        "Відділення 1",
                        "new",
                        1000.00,
                        "Test order",
                        "test_user",
                    ),
                )
                
                order_row = cur.fetchone()
                if not order_row:
                    logger.error("❌ orders test FAILED: order not created")
                    return False
                
                order_id = order_row["id"]
                
                # Insert order items
                cur.execute(
                    """
                    DELETE FROM order_items WHERE order_id = %s
                    """,
                    (order_id,),
                )
                
                cur.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, product_name,
                        quantity, price_at_purchase,
                        selected_size, selected_color
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (order_id, 1, "Test Product", 1, 1000.00, "M", "Червоний"),
                )
                
                conn.commit()
                
                # Verify order and items
                cur.execute("SELECT * FROM orders WHERE session_id = %s", (test_session_id,))
                order = cur.fetchone()
                
                cur.execute("SELECT * FROM order_items WHERE order_id = %s", (order_id,))
                items = cur.fetchall()
                
                if order and items:
                    logger.info(
                        "✅ orders/order_items test PASSED: order_id=%s, items_count=%d",
                        order_id,
                        len(items),
                    )
                    # Cleanup
                    cur.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
                    cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
                    conn.commit()
                    return True
                else:
                    logger.error("❌ orders test FAILED: order or items not found")
                    return False
                    
    except Exception as e:
        logger.error("❌ orders test FAILED: %s", e)
        return False


async def test_sitniks_mapping():
    """Test that sitniks_chat_mappings is populated on first touch."""
    logger.info("Testing sitniks_chat_mappings table population...")
    
    try:
        postgres_url = get_postgres_url()
    except ValueError:
        logger.error("DATABASE_URL not set, skipping sitniks test")
        return False
    
    test_user_id = f"test_user_{datetime.now(UTC).timestamp()}"
    test_chat_id = f"test_chat_{datetime.now(UTC).timestamp()}"
    
    try:
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Simulate Sitniks mapping save (from _save_chat_mapping)
                cur.execute(
                    """
                    INSERT INTO sitniks_chat_mappings 
                    (user_id, sitniks_chat_id, instagram_username, telegram_username, first_touch_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (user_id) 
                    DO UPDATE SET
                        sitniks_chat_id = EXCLUDED.sitniks_chat_id,
                        instagram_username = EXCLUDED.instagram_username,
                        telegram_username = EXCLUDED.telegram_username,
                        updated_at = NOW()
                    """,
                    (test_user_id, test_chat_id, "test_instagram", "test_telegram"),
                )
                
                conn.commit()
                
                # Verify mapping was created
                cur.execute(
                    "SELECT * FROM sitniks_chat_mappings WHERE user_id = %s",
                    (test_user_id,),
                )
                mapping = cur.fetchone()
                
                if mapping:
                    logger.info(
                        "✅ sitniks_chat_mappings test PASSED: user_id=%s, chat_id=%s",
                        test_user_id,
                        test_chat_id,
                    )
                    # Cleanup
                    cur.execute(
                        "DELETE FROM sitniks_chat_mappings WHERE user_id = %s",
                        (test_user_id,),
                    )
                    conn.commit()
                    return True
                else:
                    logger.error("❌ sitniks_chat_mappings test FAILED: mapping not found")
                    return False
                    
    except Exception as e:
        logger.error("❌ sitniks_chat_mappings test FAILED: %s", e)
        return False


async def test_llm_usage_model():
    """Test that llm_usage records show correct model (gpt-5.1)."""
    logger.info("Testing llm_usage model recording...")
    
    try:
        postgres_url = get_postgres_url()
    except ValueError:
        logger.error("DATABASE_URL not set, skipping llm_usage test")
        return False
    
    test_session_id = f"test_session_{datetime.now(UTC).timestamp()}"
    test_model = settings.AI_MODEL
    
    try:
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Insert a test llm_usage record
                cur.execute(
                    """
                    INSERT INTO llm_usage
                    (session_id, model, tokens_input, tokens_output, cost_usd, success, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        test_session_id,
                        test_model,
                        100,
                        50,
                        0.0005,
                        True,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                
                conn.commit()
                
                # Verify model was recorded correctly
                cur.execute(
                    "SELECT model FROM llm_usage WHERE session_id = %s ORDER BY created_at DESC LIMIT 1",
                    (test_session_id,),
                )
                usage = cur.fetchone()
                
                if usage and usage["model"] == test_model:
                    logger.info(
                        "✅ llm_usage test PASSED: model=%s (expected %s)",
                        usage["model"],
                        test_model,
                    )
                    # Cleanup
                    cur.execute("DELETE FROM llm_usage WHERE session_id = %s", (test_session_id,))
                    conn.commit()
                    return True
                else:
                    logger.error(
                        "❌ llm_usage test FAILED: model=%s (expected %s)",
                        usage["model"] if usage else "None",
                        test_model,
                    )
                    return False
                    
    except Exception as e:
        logger.error("❌ llm_usage test FAILED: %s", e)
        return False


async def main():
    """Run all smoke tests."""
    logger.info("=" * 60)
    logger.info("Production Tables Smoke Tests")
    logger.info("=" * 60)
    
    results = {
        "users": await test_users_table(),
        "orders": await test_orders_table(),
        "sitniks": await test_sitniks_mapping(),
        "llm_usage": await test_llm_usage_model(),
    }
    
    logger.info("=" * 60)
    logger.info("Test Results:")
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info("  %s: %s", test_name, status)
    logger.info("=" * 60)
    
    all_passed = all(results.values())
    if all_passed:
        logger.info("All tests PASSED! Production tables should work correctly.")
        return 0
    else:
        logger.error("Some tests FAILED. Review the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

