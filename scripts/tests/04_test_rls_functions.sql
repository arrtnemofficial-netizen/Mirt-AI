-- ============================================================================
-- MIRT AI - Supabase Table Tests: RLS & FUNCTIONS
-- ============================================================================
-- Run in Supabase SQL Editor
-- Tests: Row Level Security, Database Functions, Triggers
-- ============================================================================

-- ============================================================================
-- TEST SUITE 17: ROW LEVEL SECURITY (RLS)
-- ============================================================================

-- TEST 17.1: Check RLS status for all tables
SELECT 
    schemaname,
    tablename,
    rowsecurity as rls_enabled
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY tablename;

-- TEST 17.2: List all RLS policies
SELECT 
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd
FROM pg_policies 
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- TEST 17.3: Verify products has public read access
-- This should work even with RLS enabled
SELECT COUNT(*) as product_count FROM products;

-- TEST 17.4: Check if service_role bypasses RLS (it should)
-- Run this to confirm you're using service_role
SELECT current_user, session_user;

-- ============================================================================
-- TEST SUITE 18: DATABASE FUNCTIONS
-- ============================================================================

-- TEST 18.1: Test update_updated_at_column trigger function exists
SELECT 
    proname as function_name,
    prosrc IS NOT NULL as has_source
FROM pg_proc 
WHERE proname = 'update_updated_at_column';

-- TEST 18.2: Test calculate_profile_completeness function
SELECT 
    proname as function_name,
    pronargs as num_args
FROM pg_proc 
WHERE proname = 'calculate_profile_completeness';

-- TEST 18.3: Test apply_memory_decay function
SELECT 
    proname as function_name,
    prorettype::regtype as return_type
FROM pg_proc 
WHERE proname = 'apply_memory_decay';

-- TEST 18.4: Test search_memories function exists
SELECT 
    proname as function_name,
    pronargs as num_args
FROM pg_proc 
WHERE proname = 'search_memories';

-- TEST 18.5: Call apply_memory_decay
SELECT apply_memory_decay() as rows_affected;

-- ============================================================================
-- TEST SUITE 19: TRIGGERS
-- ============================================================================

-- TEST 19.1: List all triggers
SELECT 
    trigger_schema,
    trigger_name,
    event_manipulation,
    event_object_table,
    action_timing
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;

-- TEST 19.2: Test profile completeness trigger
-- Insert a profile and check if completeness_score is auto-calculated
INSERT INTO mirt_profiles (user_id, child_profile)
VALUES ('test_trigger_user', '{"height_cm": 128}'::jsonb)
ON CONFLICT (user_id) DO UPDATE SET child_profile = EXCLUDED.child_profile;

SELECT user_id, completeness_score 
FROM mirt_profiles 
WHERE user_id = 'test_trigger_user';
-- Expected: completeness_score > 0

-- TEST 19.3: Test updated_at trigger on crm_orders
UPDATE crm_orders SET status = 'processing' 
WHERE external_id = 'test_crm_session_001_1702300000';

SELECT external_id, updated_at 
FROM crm_orders 
WHERE external_id = 'test_crm_session_001_1702300000';
-- Expected: updated_at should be very recent

-- ============================================================================
-- TEST SUITE 20: INDEXES
-- ============================================================================

-- TEST 20.1: List all indexes
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

-- TEST 20.2: Check if vector indexes exist
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE indexdef LIKE '%vector%' OR indexdef LIKE '%hnsw%';

-- TEST 20.3: Check products indexes
SELECT indexname FROM pg_indexes WHERE tablename = 'products';

-- TEST 20.4: Check mirt_memories indexes
SELECT indexname FROM pg_indexes WHERE tablename = 'mirt_memories';

-- ============================================================================
-- TEST SUITE 21: CONSTRAINTS
-- ============================================================================

-- TEST 21.1: List all foreign keys
SELECT
    tc.table_name, 
    kcu.column_name, 
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name 
FROM 
    information_schema.table_constraints AS tc 
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
      AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public';

-- TEST 21.2: List all unique constraints
SELECT
    tc.table_name,
    tc.constraint_name,
    kcu.column_name
FROM 
    information_schema.table_constraints AS tc 
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'UNIQUE' AND tc.table_schema = 'public';

-- TEST 21.3: List check constraints
SELECT
    tc.table_name,
    tc.constraint_name,
    cc.check_clause
FROM 
    information_schema.table_constraints AS tc 
    JOIN information_schema.check_constraints AS cc
      ON tc.constraint_name = cc.constraint_name
WHERE tc.constraint_type = 'CHECK' AND tc.table_schema = 'public'
AND cc.check_clause NOT LIKE '%NOT NULL%';

-- TEST 21.4: Test crm_orders status check constraint
-- This should FAIL:
-- INSERT INTO crm_orders (session_id, external_id, status) 
-- VALUES ('test', 'test', 'invalid_status');
-- ERROR: new row violates check constraint "crm_orders_status_check"

-- ============================================================================
-- TEST SUITE 22: EXTENSIONS
-- ============================================================================

-- TEST 22.1: List installed extensions
SELECT extname, extversion FROM pg_extension ORDER BY extname;

-- TEST 22.2: Check pgvector is installed
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
-- Expected: 1 row with 'vector'

-- TEST 22.3: Check pgcrypto (for gen_random_uuid)
SELECT extname FROM pg_extension WHERE extname = 'pgcrypto';

-- ============================================================================
-- TEST SUITE 23: ENUMS
-- ============================================================================

-- TEST 23.1: List all enum types
SELECT 
    t.typname as enum_name,
    e.enumlabel as enum_value
FROM pg_type t 
JOIN pg_enum e ON t.oid = e.enumtypid  
JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
ORDER BY t.typname, e.enumsortorder;

-- TEST 23.2: Check trace_status enum values
SELECT enumlabel FROM pg_enum 
WHERE enumtypid = 'trace_status'::regtype
ORDER BY enumsortorder;
-- Expected: SUCCESS, ERROR, BLOCKED, ESCALATED

-- TEST 23.3: Check error_category enum values
SELECT enumlabel FROM pg_enum 
WHERE enumtypid = 'error_category'::regtype
ORDER BY enumsortorder;
-- Expected: SCHEMA, BUSINESS, SAFETY, SYSTEM

-- ============================================================================
-- TEST SUITE 24: TABLE STATISTICS
-- ============================================================================

-- TEST 24.1: Row counts for all tables
SELECT 
    schemaname,
    relname as table_name,
    n_live_tup as row_count
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_live_tup DESC;

-- TEST 24.2: Table sizes
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- TEST 24.3: Index usage
SELECT 
    schemaname,
    relname as table_name,
    indexrelname as index_name,
    idx_scan as times_used,
    idx_tup_read as rows_read
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC
LIMIT 20;

-- ============================================================================
-- CLEANUP TRIGGER TEST DATA
-- ============================================================================

-- DELETE FROM mirt_profiles WHERE user_id = 'test_trigger_user';

-- ============================================================================
-- SUMMARY: Expected Results
-- ============================================================================
-- TEST 17.x: RLS policies configured ✓
-- TEST 18.x: Database functions exist ✓
-- TEST 19.x: Triggers work ✓
-- TEST 20.x: Indexes created ✓
-- TEST 21.x: Constraints defined ✓
-- TEST 22.x: Extensions installed ✓
-- TEST 23.x: Enums defined ✓
-- TEST 24.x: Statistics available ✓
