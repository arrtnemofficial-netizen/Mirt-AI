-- ============================================================================
-- MIRT AI - COMPLETE DATABASE SCHEMA FOR POSTGRESQL (RAILWAY)
-- ============================================================================
-- Запустіть цей скрипт для створення всіх таблиць в PostgreSQL
-- 
-- ВАЖЛИВО: Цей скрипт є IDEMPOTENT - його можна запускати багато разів
-- ============================================================================

-- Enable required extensions (with error handling)
DO $$ 
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
    RAISE NOTICE '✅ vector extension enabled';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE '⚠️  vector extension not available (pgvector not installed). Tables with VECTOR columns will be created but embeddings will not work.';
END $$;

-- pg_cron is optional, skip if not available
DO $$ 
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
    RAISE NOTICE '✅ pg_cron extension enabled';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE '⚠️  pg_cron extension not available, skipping...';
END $$;

-- ============================================================================
-- 1. PRODUCTS TABLE
-- ============================================================================
-- Check if vector extension is available
DO $$ 
DECLARE
    has_vector BOOLEAN := FALSE;
BEGIN
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_vector;
    
    IF has_vector THEN
        -- Create with VECTOR column
        EXECUTE 'CREATE TABLE IF NOT EXISTS products (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            sizes TEXT[] NOT NULL DEFAULT ''{}'',
            colors TEXT[] NOT NULL DEFAULT ''{}'',
            photo_url TEXT,
            sku TEXT UNIQUE,
            price_by_size JSONB,
            embedding VECTOR(1536),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )';
    ELSE
        -- Create without VECTOR column
        EXECUTE 'CREATE TABLE IF NOT EXISTS products (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            sizes TEXT[] NOT NULL DEFAULT ''{}'',
            colors TEXT[] NOT NULL DEFAULT ''{}'',
            photo_url TEXT,
            sku TEXT UNIQUE,
            price_by_size JSONB,
            embedding BYTEA,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )';
        RAISE NOTICE '⚠️  products.embedding created as BYTEA (vector extension not available)';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

-- ============================================================================
-- 2. ORDERS TABLE (with user_nickname!)
-- ============================================================================
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_nickname TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    customer_city TEXT,
    delivery_method TEXT,
    delivery_address TEXT,
    sitniks_chat_id TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0,
    currency TEXT DEFAULT 'UAH',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_session_id ON orders(session_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_nickname ON orders(user_nickname) WHERE user_nickname IS NOT NULL;

-- Add columns if they don't exist (for existing tables)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'user_nickname') THEN
        ALTER TABLE orders ADD COLUMN user_nickname TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'sitniks_chat_id') THEN
        ALTER TABLE orders ADD COLUMN sitniks_chat_id TEXT;
    END IF;
END $$;

-- ============================================================================
-- 3. ORDER ITEMS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    order_id BIGINT REFERENCES orders(id) ON DELETE CASCADE,
    product_id BIGINT REFERENCES products(id),
    product_name TEXT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    price_at_purchase NUMERIC(10, 2) NOT NULL,
    selected_size TEXT,
    selected_color TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);

-- ============================================================================
-- 4. CRM ORDERS TABLE (Sitniks integration)
-- ============================================================================
CREATE TABLE IF NOT EXISTS crm_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    external_id TEXT NOT NULL UNIQUE,
    crm_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    order_data JSONB,
    metadata JSONB,
    task_id TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT crm_orders_status_check CHECK (status IN (
        'pending', 'queued', 'created', 'processing', 
        'shipped', 'delivered', 'cancelled', 'failed'
    ))
);

CREATE INDEX IF NOT EXISTS idx_crm_orders_session_id ON crm_orders(session_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_external_id ON crm_orders(external_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_status ON crm_orders(status);

-- ============================================================================
-- 5. SITNIKS CHAT MAPPINGS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS sitniks_chat_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    instagram_username TEXT,
    telegram_username TEXT,
    sitniks_chat_id TEXT UNIQUE,
    sitniks_manager_id INTEGER,
    current_status TEXT,
    first_touch_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_user_id ON sitniks_chat_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_instagram ON sitniks_chat_mappings(instagram_username) WHERE instagram_username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_telegram ON sitniks_chat_mappings(telegram_username) WHERE telegram_username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_chat_id ON sitniks_chat_mappings(sitniks_chat_id) WHERE sitniks_chat_id IS NOT NULL;

COMMENT ON TABLE sitniks_chat_mappings IS 'Links MIRT users to Sitniks CRM chat IDs for status updates';

-- ============================================================================
-- 6. MIRT PROFILES TABLE (Memory System)
-- ============================================================================
CREATE TABLE IF NOT EXISTS mirt_profiles (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT UNIQUE NOT NULL,
    child_profile JSONB DEFAULT '{}'::JSONB,
    style_preferences JSONB DEFAULT '{}'::JSONB,
    logistics JSONB DEFAULT '{}'::JSONB,
    commerce JSONB DEFAULT '{}'::JSONB,
    sitniks_chat_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    completeness_score FLOAT DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_mirt_profiles_user_id ON mirt_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_profiles_last_seen ON mirt_profiles(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_mirt_profiles_sitniks ON mirt_profiles(sitniks_chat_id) WHERE sitniks_chat_id IS NOT NULL;

-- Add sitniks_chat_id if table exists but column doesn't
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'mirt_profiles' AND column_name = 'sitniks_chat_id') THEN
        ALTER TABLE mirt_profiles ADD COLUMN sitniks_chat_id TEXT;
    END IF;
END $$;

-- ============================================================================
-- 7. MIRT MEMORIES TABLE (Fluid Memory)
-- ============================================================================
-- Check if vector extension is available
DO $$ 
DECLARE
    has_vector BOOLEAN := FALSE;
BEGIN
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_vector;
    
    IF has_vector THEN
        -- Create with VECTOR column
        EXECUTE 'CREATE TABLE IF NOT EXISTS mirt_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            session_id TEXT,
            content TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            category TEXT NOT NULL,
            importance FLOAT NOT NULL DEFAULT 0.5,
            surprise FLOAT NOT NULL DEFAULT 0.5,
            confidence FLOAT NOT NULL DEFAULT 0.8,
            ttl_days INT,
            decay_rate FLOAT DEFAULT 0.01,
            embedding VECTOR(1536),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            version INT DEFAULT 1,
            superseded_by UUID,
            is_active BOOLEAN DEFAULT TRUE
        )';
    ELSE
        -- Create without VECTOR column
        EXECUTE 'CREATE TABLE IF NOT EXISTS mirt_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            session_id TEXT,
            content TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            category TEXT NOT NULL,
            importance FLOAT NOT NULL DEFAULT 0.5,
            surprise FLOAT NOT NULL DEFAULT 0.5,
            confidence FLOAT NOT NULL DEFAULT 0.8,
            ttl_days INT,
            decay_rate FLOAT DEFAULT 0.01,
            embedding BYTEA,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            version INT DEFAULT 1,
            superseded_by UUID,
            is_active BOOLEAN DEFAULT TRUE
        )';
        RAISE NOTICE '⚠️  mirt_memories.embedding created as BYTEA (vector extension not available)';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_id ON mirt_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_active ON mirt_memories(user_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_mirt_memories_importance ON mirt_memories(importance DESC) WHERE is_active = TRUE;

-- ============================================================================
-- 8. MIRT MEMORY SUMMARIES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS mirt_memory_summaries (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT,
    product_id BIGINT,
    session_id TEXT,
    summary_type TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    key_facts TEXT[],
    facts_count INT DEFAULT 0,
    time_range_start TIMESTAMPTZ,
    time_range_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_current BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_mirt_summaries_user ON mirt_memory_summaries(user_id) WHERE is_current = TRUE;

-- ============================================================================
-- 9. USERS TABLE (for message_store compatibility)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT UNIQUE NOT NULL,
    username TEXT,
    telegram_username TEXT,
    instagram_username TEXT,
    summary TEXT,
    tags TEXT[] DEFAULT '{}',
    last_interaction_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_username) WHERE telegram_username IS NOT NULL;

-- Add columns if they don't exist
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'telegram_username') THEN
        ALTER TABLE users ADD COLUMN telegram_username TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'instagram_username') THEN
        ALTER TABLE users ADD COLUMN instagram_username TEXT;
    END IF;
END $$;

-- ============================================================================
-- 10. MESSAGES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at DESC);

-- ============================================================================
-- 11. LLM USAGE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_usage (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT,
    session_id TEXT,
    model TEXT NOT NULL,
    tokens_input INT NOT NULL DEFAULT 0,
    tokens_output INT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    latency_ms INT,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_user_id ON llm_usage(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_usage_session_id ON llm_usage(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at DESC);

-- ============================================================================
-- 12. LLM TRACES TABLE
-- ============================================================================
-- Create ENUMs for status and error categorization
DO $$ BEGIN
    CREATE TYPE trace_status AS ENUM ('SUCCESS', 'ERROR', 'BLOCKED', 'ESCALATED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE error_category AS ENUM ('SCHEMA', 'BUSINESS', 'SAFETY', 'SYSTEM');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create the main traces table
CREATE TABLE IF NOT EXISTS public.llm_traces (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    session_id text NOT NULL,
    trace_id uuid NOT NULL,
    node_name text NOT NULL,
    state_name text,
    prompt_key text,
    prompt_version text,
    prompt_label text,
    input_snapshot jsonb,
    output_snapshot jsonb,
    status trace_status NOT NULL DEFAULT 'SUCCESS',
    error_category error_category,
    error_message text,
    latency_ms float,
    tokens_in int,
    tokens_out int,
    cost float,
    model_name text
);

CREATE INDEX IF NOT EXISTS idx_llm_traces_session ON llm_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_traces_created ON llm_traces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_traces_trace_id ON llm_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_llm_traces_status ON llm_traces(status) WHERE status != 'SUCCESS';

-- ============================================================================
-- 13. AGENT SESSIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_sessions (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    session_id TEXT UNIQUE NOT NULL,
    state JSONB,
    order_id TEXT,
    order_status TEXT,
    sitniks_chat_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_session_id ON agent_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_order_status ON agent_sessions(order_status) WHERE order_status IS NOT NULL;

-- Add sitniks_chat_id if table exists but column doesn't
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_sessions' AND column_name = 'sitniks_chat_id') THEN
        ALTER TABLE agent_sessions ADD COLUMN sitniks_chat_id TEXT;
    END IF;
END $$;

-- ============================================================================
-- 14. WEBHOOK DEDUPE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.webhook_dedupe (
    id bigint generated by default as identity primary key,
    dedupe_key text not null unique,
    processed_at timestamptz not null default now(),
    expires_at timestamptz not null,
    constraint webhook_dedupe_expires_at_check check (expires_at > processed_at)
);

CREATE INDEX IF NOT EXISTS idx_webhook_dedupe_expires_at ON public.webhook_dedupe using btree (expires_at);
CREATE INDEX IF NOT EXISTS idx_webhook_dedupe_processed_at ON public.webhook_dedupe using btree (processed_at);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to all tables with updated_at
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT table_name FROM information_schema.columns 
               WHERE table_schema = 'public' AND column_name = 'updated_at'
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_updated_at ON %I', tbl);
        EXECUTE format('CREATE TRIGGER trg_updated_at BEFORE UPDATE ON %I 
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()', tbl);
    END LOOP;
END $$;

-- Webhook dedupe trigger
DROP TRIGGER IF EXISTS trg_webhook_dedupe_updated_at ON public.webhook_dedupe;
CREATE TRIGGER trg_webhook_dedupe_updated_at
    BEFORE UPDATE ON public.webhook_dedupe
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function: summarize_inactive_users
DROP FUNCTION IF EXISTS summarize_inactive_users();

CREATE OR REPLACE FUNCTION summarize_inactive_users()
RETURNS TABLE (
    out_user_id TEXT,
    out_username TEXT,
    out_last_interaction_at TIMESTAMPTZ
) AS $$
DECLARE
    affected_count INT := 0;
BEGIN
    WITH inactive_users AS (
        SELECT u.user_id, u.username, u.last_interaction_at, u.tags
        FROM users u
        WHERE 
            u.last_interaction_at < NOW() - INTERVAL '3 days'
            AND NOT (COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['needs_summary']::TEXT[])
            AND NOT (COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['summarized']::TEXT[])
    ),
    updated AS (
        UPDATE users u2
        SET 
            tags = array_append(
                COALESCE(u2.tags, ARRAY[]::TEXT[]),
                'needs_summary'
            ),
            updated_at = NOW()
        FROM inactive_users iu
        WHERE u2.user_id = iu.user_id
        RETURNING u2.user_id, u2.username, u2.last_interaction_at
    )
    SELECT COUNT(*) INTO affected_count FROM updated;
    
    RAISE NOTICE 'summarize_inactive_users: marked % users for summarization', affected_count;
    
    RETURN QUERY
    SELECT u.user_id, u.username, u.last_interaction_at
    FROM users u
    WHERE COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['needs_summary']::TEXT[]
    ORDER BY u.last_interaction_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Function: cleanup_expired_webhook_dedupe
CREATE OR REPLACE FUNCTION cleanup_expired_webhook_dedupe()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count integer;
BEGIN
    DELETE FROM public.webhook_dedupe
    WHERE expires_at < now();
    
    GET DIAGNOSTICS deleted_count = row_count;
    
    RETURN deleted_count;
END;
$$;

-- ============================================================================
-- RLS POLICIES (Optional for Railway - can be disabled)
-- ============================================================================
-- Note: For Railway PostgreSQL, RLS is usually not needed unless you have multiple tenants
-- Uncomment if you need RLS:

/*
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE sitniks_chat_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE mirt_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE mirt_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE mirt_memory_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_dedupe ENABLE ROW LEVEL SECURITY;

-- Create permissive policies
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON products FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON orders FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON order_items FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON crm_orders FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON sitniks_chat_mappings FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON mirt_profiles FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON mirt_memories FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON mirt_memory_summaries FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON users FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON messages FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON llm_usage FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON agent_sessions FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON llm_traces FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS "Allow all for service role" ON webhook_dedupe FOR ALL USING (true);
*/

-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '✅ Schema creation complete!';
    RAISE NOTICE '   Tables created/updated:';
    RAISE NOTICE '   - products';
    RAISE NOTICE '   - orders (with user_nickname, sitniks_chat_id)';
    RAISE NOTICE '   - order_items';
    RAISE NOTICE '   - crm_orders';
    RAISE NOTICE '   - sitniks_chat_mappings';
    RAISE NOTICE '   - mirt_profiles (with sitniks_chat_id)';
    RAISE NOTICE '   - mirt_memories';
    RAISE NOTICE '   - mirt_memory_summaries';
    RAISE NOTICE '   - users';
    RAISE NOTICE '   - messages';
    RAISE NOTICE '   - llm_usage';
    RAISE NOTICE '   - llm_traces';
    RAISE NOTICE '   - agent_sessions (with sitniks_chat_id)';
    RAISE NOTICE '   - webhook_dedupe';
    RAISE NOTICE '   Functions:';
    RAISE NOTICE '   - summarize_inactive_users()';
    RAISE NOTICE '   - cleanup_expired_webhook_dedupe()';
END $$;

