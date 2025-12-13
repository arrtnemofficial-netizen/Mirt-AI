-- ============================================================================
-- MIRT AI - Supabase Table Tests: CRM & OBSERVABILITY
-- ============================================================================
-- Run in Supabase SQL Editor
-- Tests: crm_orders, sitniks_chat_mappings, llm_traces, llm_usage
-- ============================================================================

-- ============================================================================
-- TEST SUITE 12: CRM_ORDERS TABLE
-- ============================================================================

-- TEST 12.1: Insert pending order
INSERT INTO crm_orders (session_id, external_id, crm_order_id, status, order_data, metadata)
VALUES (
    'test_crm_session_001',
    'test_crm_session_001_1702300000',
    NULL,  -- Not yet synced to CRM
    'pending',
    '{
        "customer": {
            "name": "Тестовий Клієнт",
            "phone": "+380991234567",
            "city": "Київ",
            "nova_poshta": "Відділення №52"
        },
        "products": [
            {"name": "Костюм Ритм", "size": "140-146", "price": 1975, "quantity": 1}
        ],
        "total": 1975,
        "payment_method": "full"
    }'::jsonb,
    '{"source": "telegram", "test": true}'::jsonb
)
ON CONFLICT (external_id) DO UPDATE SET status = 'pending', updated_at = NOW();

-- TEST 12.2: Select pending order
SELECT 
    external_id,
    status,
    order_data->'customer'->>'name' as customer_name,
    order_data->'total' as total,
    created_at
FROM crm_orders 
WHERE session_id = 'test_crm_session_001';

-- TEST 12.3: Update to queued status
UPDATE crm_orders 
SET status = 'queued', task_id = 'celery-task-123'
WHERE external_id = 'test_crm_session_001_1702300000';

-- TEST 12.4: Simulate CRM sync - add crm_order_id
UPDATE crm_orders 
SET 
    status = 'created',
    crm_order_id = 'SNITKIX-12345',
    metadata = metadata || '{"synced_at": "2024-12-11T10:00:00Z"}'::jsonb
WHERE external_id = 'test_crm_session_001_1702300000';

-- TEST 12.5: Verify CRM sync
SELECT 
    external_id,
    crm_order_id,
    status,
    metadata->>'synced_at' as synced_at
FROM crm_orders 
WHERE external_id = 'test_crm_session_001_1702300000';
-- Expected: crm_order_id = 'SNITKIX-12345', status = 'created'

-- TEST 12.6: Update order status (simulate shipping)
UPDATE crm_orders 
SET status = 'shipped', metadata = metadata || '{"tracking": "59000123456789"}'::jsonb
WHERE crm_order_id = 'SNITKIX-12345';

-- TEST 12.7: Query orders by status
SELECT external_id, status, crm_order_id 
FROM crm_orders 
WHERE status IN ('created', 'processing', 'shipped')
ORDER BY created_at DESC;

-- TEST 12.8: Failed order test
INSERT INTO crm_orders (session_id, external_id, status, error_message, order_data)
VALUES (
    'test_crm_session_002',
    'test_crm_session_002_1702300001',
    'failed',
    'CRM API timeout after 3 retries',
    '{"error_context": "test"}'::jsonb
);

-- TEST 12.9: Query failed orders
SELECT external_id, status, error_message, created_at
FROM crm_orders 
WHERE status = 'failed'
ORDER BY created_at DESC;

-- TEST 12.10: Count orders by status
SELECT status, COUNT(*) as count 
FROM crm_orders 
GROUP BY status
ORDER BY count DESC;

-- ============================================================================
-- TEST SUITE 13: SITNIKS_CHAT_MAPPINGS TABLE
-- ============================================================================

-- TEST 13.1: Insert chat mapping
INSERT INTO sitniks_chat_mappings (
    user_id, instagram_username, telegram_username, 
    sitniks_chat_id, sitniks_manager_id, current_status, first_touch_at
)
VALUES (
    'test_sitniks_user_001',
    'test_instagram',
    'test_telegram',
    'sitniks-chat-12345',
    101,  -- AI Manager ID
    'Взято в роботу',
    NOW()
)
ON CONFLICT (sitniks_chat_id) DO UPDATE SET 
    current_status = EXCLUDED.current_status,
    updated_at = NOW();

-- TEST 13.2: Select mapping
SELECT 
    user_id,
    telegram_username,
    sitniks_chat_id,
    current_status,
    sitniks_manager_id
FROM sitniks_chat_mappings 
WHERE user_id = 'test_sitniks_user_001';

-- TEST 13.3: Update status to "Виставлено рахунок"
UPDATE sitniks_chat_mappings 
SET current_status = 'Виставлено рахунок', updated_at = NOW()
WHERE user_id = 'test_sitniks_user_001';

-- TEST 13.4: Verify status update
SELECT current_status FROM sitniks_chat_mappings 
WHERE user_id = 'test_sitniks_user_001';
-- Expected: 'Виставлено рахунок'

-- TEST 13.5: Update manager on escalation
UPDATE sitniks_chat_mappings 
SET 
    current_status = 'AI Увага',
    sitniks_manager_id = 102  -- Human manager
WHERE user_id = 'test_sitniks_user_001';

-- TEST 13.6: Find by telegram username
SELECT * FROM sitniks_chat_mappings 
WHERE telegram_username = 'test_telegram';

-- TEST 13.7: Find by instagram username
SELECT * FROM sitniks_chat_mappings 
WHERE instagram_username = 'test_instagram';

-- TEST 13.8: List all chats by status
SELECT current_status, COUNT(*) as count
FROM sitniks_chat_mappings
GROUP BY current_status;

-- ============================================================================
-- TEST SUITE 14: LLM_TRACES TABLE
-- ============================================================================

-- TEST 14.1: Insert successful trace
INSERT INTO llm_traces (
    session_id, trace_id, node_name, state_name, 
    prompt_key, prompt_version, prompt_label,
    input_snapshot, output_snapshot,
    status, latency_ms, tokens_in, tokens_out, cost, model_name
)
VALUES (
    'test_trace_session_001',
    gen_random_uuid(),
    'agent_node',
    'STATE_4_OFFER',
    'state.STATE_4_OFFER',
    '1.2.0',
    'prod',
    '{"user_message": "хочу костюм на 140", "has_image": false}'::jsonb,
    '{"response": "Раджу Костюм Ритм, розмір 140-146", "intent": "SIZE_HELP"}'::jsonb,
    'SUCCESS',
    2500.5,
    850,
    120,
    0.0025,
    'gpt-4o'
);

-- TEST 14.2: Insert error trace
INSERT INTO llm_traces (
    session_id, trace_id, node_name, state_name,
    status, error_category, error_message,
    latency_ms, model_name
)
VALUES (
    'test_trace_session_001',
    gen_random_uuid(),
    'vision_node',
    'STATE_2_VISION',
    'ERROR',
    'SYSTEM',
    'OpenAI API timeout after 30s',
    30000,
    'gpt-4o'
);

-- TEST 14.3: Insert blocked trace (moderation)
INSERT INTO llm_traces (
    session_id, trace_id, node_name,
    input_snapshot, status, error_category, error_message,
    model_name
)
VALUES (
    'test_trace_session_002',
    gen_random_uuid(),
    'moderation_node',
    '{"user_message": "inappropriate content"}'::jsonb,
    'BLOCKED',
    'SAFETY',
    'Content blocked by moderation',
    'text-moderation-latest'
);

-- TEST 14.4: Insert escalation trace
INSERT INTO llm_traces (
    session_id, trace_id, node_name, state_name,
    output_snapshot, status,
    latency_ms, model_name
)
VALUES (
    'test_trace_session_001',
    gen_random_uuid(),
    'escalation_node',
    'STATE_6_ESCALATION',
    '{"reason": "Клієнт просить знижку понад 10%", "target": "human_manager"}'::jsonb,
    'ESCALATED',
    150,
    'gpt-4o'
);

-- TEST 14.5: Select traces for session
SELECT 
    node_name,
    state_name,
    status,
    latency_ms,
    tokens_in + tokens_out as total_tokens,
    created_at
FROM llm_traces 
WHERE session_id = 'test_trace_session_001'
ORDER BY created_at;

-- TEST 14.6: Count traces by status
SELECT status, COUNT(*) as count
FROM llm_traces
GROUP BY status
ORDER BY count DESC;

-- TEST 14.7: Count errors by category
SELECT error_category, COUNT(*) as count, AVG(latency_ms) as avg_latency
FROM llm_traces
WHERE status != 'SUCCESS' AND error_category IS NOT NULL
GROUP BY error_category;

-- TEST 14.8: Average latency by node
SELECT 
    node_name,
    COUNT(*) as calls,
    ROUND(AVG(latency_ms)::numeric, 2) as avg_latency_ms,
    ROUND(MAX(latency_ms)::numeric, 2) as max_latency_ms
FROM llm_traces
WHERE status = 'SUCCESS'
GROUP BY node_name
ORDER BY avg_latency_ms DESC;

-- TEST 14.9: Token usage per session
SELECT 
    session_id,
    SUM(tokens_in) as total_tokens_in,
    SUM(tokens_out) as total_tokens_out,
    SUM(cost) as total_cost
FROM llm_traces
WHERE session_id LIKE 'test_trace%'
GROUP BY session_id;

-- TEST 14.10: Recent errors (last hour simulation)
SELECT 
    session_id,
    node_name,
    error_category,
    error_message,
    created_at
FROM llm_traces
WHERE status = 'ERROR'
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- TEST SUITE 15: LLM_USAGE TABLE
-- ============================================================================

-- TEST 15.1: Insert usage record
INSERT INTO llm_usage (user_id, model, tokens_in, tokens_out, cost, created_at)
VALUES 
    (999901, 'gpt-4o', 1200, 350, 0.0045, NOW()),
    (999901, 'gpt-4o', 800, 200, 0.0028, NOW() - interval '1 hour'),
    (999901, 'gpt-4o-mini', 500, 100, 0.0005, NOW() - interval '2 hours'),
    (999902, 'gpt-4o', 2000, 500, 0.0075, NOW());

-- TEST 15.2: Usage per user
SELECT 
    user_id,
    COUNT(*) as requests,
    SUM(tokens_in) as total_in,
    SUM(tokens_out) as total_out,
    ROUND(SUM(cost)::numeric, 4) as total_cost
FROM llm_usage
WHERE user_id IN (999901, 999902)
GROUP BY user_id;

-- TEST 15.3: Usage per model
SELECT 
    model,
    COUNT(*) as requests,
    SUM(tokens_in + tokens_out) as total_tokens,
    ROUND(SUM(cost)::numeric, 4) as total_cost
FROM llm_usage
GROUP BY model
ORDER BY total_cost DESC;

-- TEST 15.4: Daily aggregation
SELECT 
    DATE(created_at) as date,
    COUNT(*) as requests,
    SUM(tokens_in + tokens_out) as total_tokens,
    ROUND(SUM(cost)::numeric, 4) as total_cost
FROM llm_usage
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- TEST 15.5: Top users by cost
SELECT 
    user_id,
    ROUND(SUM(cost)::numeric, 4) as total_cost,
    COUNT(*) as requests
FROM llm_usage
GROUP BY user_id
ORDER BY total_cost DESC
LIMIT 10;

-- ============================================================================
-- TEST SUITE 16: CHECKPOINTS TABLES (LangGraph)
-- ============================================================================

-- TEST 16.1: Check if checkpoints table exists and has data
SELECT 
    thread_id,
    checkpoint_ns,
    LEFT(checkpoint_id, 20) as checkpoint_id_short,
    created_at
FROM checkpoints
LIMIT 5;

-- TEST 16.2: Count checkpoints per thread
SELECT 
    thread_id,
    COUNT(*) as checkpoint_count
FROM checkpoints
GROUP BY thread_id
ORDER BY checkpoint_count DESC
LIMIT 10;

-- TEST 16.3: Check checkpoint_blobs
SELECT COUNT(*) as blob_count FROM checkpoint_blobs;

-- TEST 16.4: Check checkpoint_writes
SELECT COUNT(*) as write_count FROM checkpoint_writes;

-- TEST 16.5: Recent checkpoints
SELECT 
    thread_id,
    checkpoint_ns,
    created_at
FROM checkpoints
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- CLEANUP: Remove test CRM/observability data
-- ============================================================================

-- DELETE FROM llm_usage WHERE user_id IN (999901, 999902);
-- DELETE FROM llm_traces WHERE session_id LIKE 'test_trace%';
-- DELETE FROM sitniks_chat_mappings WHERE user_id = 'test_sitniks_user_001';
-- DELETE FROM crm_orders WHERE session_id LIKE 'test_crm%';

-- ============================================================================
-- SUMMARY: Expected Results
-- ============================================================================
-- TEST 12.x: crm_orders CRUD + status flow works ✓
-- TEST 13.x: sitniks_chat_mappings works ✓
-- TEST 14.x: llm_traces with all statuses works ✓
-- TEST 15.x: llm_usage aggregation works ✓
-- TEST 16.x: checkpoints tables exist and work ✓
