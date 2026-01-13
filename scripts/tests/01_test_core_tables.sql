-- ============================================================================
-- MIRT AI - Supabase Table Tests: CORE TABLES
-- ============================================================================
-- Run in Supabase SQL Editor
-- Expected: All queries return data or "INSERT 0 1" success
-- ============================================================================

-- ============================================================================
-- TEST SUITE 1: USERS TABLE
-- ============================================================================

-- TEST 1.1: Insert test user
INSERT INTO users (id, external_id, username, first_name, created_at)
VALUES (999901, 'test_user_001', 'test_username', 'TestUser', NOW())
ON CONFLICT (id) DO NOTHING;

-- TEST 1.2: Select test user
SELECT * FROM users WHERE external_id = 'test_user_001';

-- TEST 1.3: Update test user
UPDATE users SET first_name = 'UpdatedTestUser' WHERE external_id = 'test_user_001';

-- TEST 1.4: Verify update
SELECT first_name FROM users WHERE external_id = 'test_user_001';
-- Expected: 'UpdatedTestUser'

-- ============================================================================
-- TEST SUITE 2: AGENT_SESSIONS TABLE
-- ============================================================================

-- TEST 2.1: Insert test session
INSERT INTO agent_sessions (session_id, state, created_at, updated_at)
VALUES (
    'test_session_001',
    '{"current_state": "STATE_0_INIT", "messages": [], "metadata": {"session_id": "test_session_001"}}'::jsonb,
    NOW(),
    NOW()
)
ON CONFLICT (session_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW();

-- TEST 2.2: Select test session
SELECT session_id, state->'current_state' as current_state 
FROM agent_sessions 
WHERE session_id = 'test_session_001';

-- TEST 2.3: Update session state
UPDATE agent_sessions 
SET state = jsonb_set(state, '{current_state}', '"STATE_4_OFFER"')
WHERE session_id = 'test_session_001';

-- TEST 2.4: Verify state update
SELECT state->'current_state' as current_state 
FROM agent_sessions 
WHERE session_id = 'test_session_001';
-- Expected: "STATE_4_OFFER"

-- TEST 2.5: Add metadata to session
UPDATE agent_sessions 
SET state = jsonb_set(state, '{metadata,customer_name}', '"Тест Юзер"')
WHERE session_id = 'test_session_001';

-- TEST 2.6: Verify metadata
SELECT state->'metadata'->'customer_name' as customer_name 
FROM agent_sessions 
WHERE session_id = 'test_session_001';
-- Expected: "Тест Юзер"

-- ============================================================================
-- TEST SUITE 3: MESSAGES TABLE
-- ============================================================================

-- TEST 3.1: Insert user message
INSERT INTO messages (session_id, user_id, role, content, tags, created_at)
VALUES (
    'test_session_001',
    'test_user_001',
    'user',
    'Привіт, хочу купити костюм',
    ARRAY['test'],
    NOW()
);

-- TEST 3.2: Insert assistant message
INSERT INTO messages (session_id, user_id, role, content, tags, created_at)
VALUES (
    'test_session_001',
    'test_user_001',
    'assistant',
    'Вітаю! Який розмір вас цікавить?',
    ARRAY['test'],
    NOW()
);

-- TEST 3.3: Select messages for session
SELECT role, content, created_at 
FROM messages 
WHERE session_id = 'test_session_001' 
ORDER BY created_at;
-- Expected: 2 rows (user + assistant)

-- TEST 3.4: Count messages by role
SELECT role, COUNT(*) as count 
FROM messages 
WHERE session_id = 'test_session_001' 
GROUP BY role;
-- Expected: user=1, assistant=1

-- TEST 3.5: Add tag to message
UPDATE messages 
SET tags = array_append(tags, 'followup-sent-1') 
WHERE session_id = 'test_session_001' AND role = 'user';

-- TEST 3.6: Filter by tag
SELECT content FROM messages 
WHERE 'followup-sent-1' = ANY(tags);
-- Expected: 1 row

-- ============================================================================
-- TEST SUITE 4: PRODUCTS TABLE
-- ============================================================================

-- TEST 4.1: Insert test product
INSERT INTO products (name, description, category, subcategory, price, sizes, colors, photo_url, sku)
VALUES (
    'Тестовий Костюм',
    'Опис тестового костюму',
    'Костюми',
    'Спортивні',
    1999.00,
    ARRAY['128-134', '134-140', '140-146'],
    ARRAY['червоний', 'синій'],
    'https://example.com/test.jpg',
    'TEST-SKU-001'
)
ON CONFLICT (sku) DO NOTHING;

-- TEST 4.2: Select test product
SELECT name, price, sizes, colors FROM products WHERE sku = 'TEST-SKU-001';

-- TEST 4.3: Search by category
SELECT name, price FROM products WHERE category = 'Костюми' LIMIT 5;

-- TEST 4.4: Search by size (array contains)
SELECT name, sizes FROM products WHERE '140-146' = ANY(sizes) LIMIT 5;

-- TEST 4.5: Search by price range
SELECT name, price FROM products WHERE price BETWEEN 1500 AND 2500 ORDER BY price;

-- TEST 4.6: Update product price
UPDATE products SET price = 2099.00, updated_at = NOW() WHERE sku = 'TEST-SKU-001';

-- TEST 4.7: Verify price update
SELECT price FROM products WHERE sku = 'TEST-SKU-001';
-- Expected: 2099.00

-- TEST 4.8: Full-text search simulation
SELECT name, description FROM products 
WHERE name ILIKE '%костюм%' OR description ILIKE '%костюм%'
LIMIT 10;

-- ============================================================================
-- TEST SUITE 5: ORDERS TABLE
-- ============================================================================

-- TEST 5.1: Insert test order
INSERT INTO orders (user_id, session_id, customer_name, customer_phone, customer_city, 
                    delivery_method, delivery_address, status, total_amount, currency, notes)
VALUES (
    'test_user_001',
    'test_session_001',
    'Тестовий Покупець',
    '+380991234567',
    'Київ',
    'nova_poshta',
    'Відділення №52',
    'new',
    1999.00,
    'UAH',
    'Тестове замовлення'
)
RETURNING id;
-- Save this ID for next tests!

-- TEST 5.2: Select test order
SELECT id, customer_name, status, total_amount 
FROM orders 
WHERE user_id = 'test_user_001' AND notes = 'Тестове замовлення';

-- TEST 5.3: Update order status
UPDATE orders SET status = 'paid', updated_at = NOW() 
WHERE user_id = 'test_user_001' AND notes = 'Тестове замовлення';

-- TEST 5.4: Verify status update
SELECT status FROM orders WHERE user_id = 'test_user_001' AND notes = 'Тестове замовлення';
-- Expected: 'paid'

-- ============================================================================
-- TEST SUITE 6: ORDER_ITEMS TABLE
-- ============================================================================

-- TEST 6.1: Get order ID for items
-- First, get the order ID from TEST 5.1

-- TEST 6.2: Insert order item (replace ORDER_ID with actual ID)
INSERT INTO order_items (order_id, product_id, product_name, quantity, price_at_purchase, selected_size, selected_color)
SELECT 
    o.id as order_id,
    p.id as product_id,
    'Тестовий Костюм' as product_name,
    1 as quantity,
    1999.00 as price_at_purchase,
    '140-146' as selected_size,
    'червоний' as selected_color
FROM orders o, products p
WHERE o.notes = 'Тестове замовлення' AND p.sku = 'TEST-SKU-001'
LIMIT 1;

-- TEST 6.3: Select order with items (JOIN test)
SELECT 
    o.id as order_id,
    o.customer_name,
    o.total_amount,
    oi.product_name,
    oi.quantity,
    oi.selected_size,
    oi.selected_color
FROM orders o
LEFT JOIN order_items oi ON o.id = oi.order_id
WHERE o.notes = 'Тестове замовлення';

-- TEST 6.4: Calculate order total from items
SELECT 
    o.id,
    o.total_amount as order_total,
    SUM(oi.price_at_purchase * oi.quantity) as calculated_total
FROM orders o
LEFT JOIN order_items oi ON o.id = oi.order_id
WHERE o.notes = 'Тестове замовлення'
GROUP BY o.id, o.total_amount;

-- ============================================================================
-- CLEANUP: Remove test data (run after tests)
-- ============================================================================

-- DELETE FROM order_items WHERE product_name = 'Тестовий Костюм';
-- DELETE FROM orders WHERE notes = 'Тестове замовлення';
-- DELETE FROM messages WHERE session_id = 'test_session_001';
-- DELETE FROM agent_sessions WHERE session_id = 'test_session_001';
-- DELETE FROM products WHERE sku = 'TEST-SKU-001';
-- DELETE FROM users WHERE external_id = 'test_user_001';

-- ============================================================================
-- SUMMARY: Expected Results
-- ============================================================================
-- TEST 1.x: users table works ✓
-- TEST 2.x: agent_sessions JSONB works ✓
-- TEST 3.x: messages with tags works ✓
-- TEST 4.x: products with arrays works ✓
-- TEST 5.x: orders CRUD works ✓
-- TEST 6.x: order_items with JOINs works ✓
