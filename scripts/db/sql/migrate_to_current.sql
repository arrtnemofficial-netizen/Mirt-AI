-- ============================================================================
-- MIRT AI - MIGRATION SCRIPT
-- ============================================================================
-- Цей скрипт ОНОВЛЮЄ існуючу БД до актуального стану
-- 
-- ЩО РОБИТЬ:
--   ✅ Додає нові таблиці (sitniks_chat_mappings, mirt_profiles, mirt_memories, etc)
--   ✅ Додає нові колонки в існуючі таблиці (user_nickname, sitniks_chat_id)
--   ⚠️ Видаляє непотрібні таблиці (mirt_messages, mirt_users)
--   ✅ Міграція даних з mirt_users → mirt_profiles
--
-- ВАЖЛИВО: Запускати в Supabase SQL Editor!
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 0: Увімкнути необхідні EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- STEP 1: Додати нові колонки в ORDERS (якщо таблиця вже є)
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 1: Updating ORDERS table...';
    
    -- user_nickname
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'orders' AND column_name = 'user_nickname') THEN
        ALTER TABLE orders ADD COLUMN user_nickname TEXT;
        RAISE NOTICE '   ✅ Added: orders.user_nickname';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: orders.user_nickname already exists';
    END IF;
    
    -- sitniks_chat_id
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'orders' AND column_name = 'sitniks_chat_id') THEN
        ALTER TABLE orders ADD COLUMN sitniks_chat_id TEXT;
        RAISE NOTICE '   ✅ Added: orders.sitniks_chat_id';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: orders.sitniks_chat_id already exists';
    END IF;
END $$;

-- ============================================================================
-- STEP 2: Додати нові колонки в AGENT_SESSIONS
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 2: Updating AGENT_SESSIONS table...';
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'agent_sessions' AND column_name = 'sitniks_chat_id') THEN
        ALTER TABLE agent_sessions ADD COLUMN sitniks_chat_id TEXT;
        RAISE NOTICE '   ✅ Added: agent_sessions.sitniks_chat_id';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: agent_sessions.sitniks_chat_id already exists';
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Додати нові колонки в USERS
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 3: Updating USERS table...';
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'users' AND column_name = 'telegram_username') THEN
        ALTER TABLE users ADD COLUMN telegram_username TEXT;
        RAISE NOTICE '   ✅ Added: users.telegram_username';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: users.telegram_username already exists';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'users' AND column_name = 'instagram_username') THEN
        ALTER TABLE users ADD COLUMN instagram_username TEXT;
        RAISE NOTICE '   ✅ Added: users.instagram_username';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: users.instagram_username already exists';
    END IF;
END $$;

-- ============================================================================
-- STEP 4: Створити SITNIKS_CHAT_MAPPINGS (нова таблиця)
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 4: Creating SITNIKS_CHAT_MAPPINGS...';
END $$;

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
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_telegram ON sitniks_chat_mappings(telegram_username) WHERE telegram_username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_instagram ON sitniks_chat_mappings(instagram_username) WHERE instagram_username IS NOT NULL;

-- ============================================================================
-- STEP 5: Створити/оновити CRM_ORDERS (якщо немає)
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 5: Creating CRM_ORDERS...';
END $$;

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
CREATE INDEX IF NOT EXISTS idx_crm_orders_created_at ON crm_orders(created_at DESC);

-- ============================================================================
-- STEP 6: Міграція mirt_users → mirt_profiles
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 6: Migrating mirt_users → mirt_profiles...';
    
    -- Перевіряємо чи є mirt_users
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_users') THEN
        -- Перевіряємо чи є mirt_profiles
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_profiles') THEN
            -- Перейменовуємо mirt_users → mirt_profiles
            ALTER TABLE mirt_users RENAME TO mirt_profiles;
            RAISE NOTICE '   ✅ Renamed: mirt_users → mirt_profiles';
            
            -- Додаємо нові колонки якщо їх немає
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'child_profile') THEN
                ALTER TABLE mirt_profiles ADD COLUMN child_profile JSONB DEFAULT '{}'::JSONB;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'style_preferences') THEN
                ALTER TABLE mirt_profiles ADD COLUMN style_preferences JSONB DEFAULT '{}'::JSONB;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'logistics') THEN
                ALTER TABLE mirt_profiles ADD COLUMN logistics JSONB DEFAULT '{}'::JSONB;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'commerce') THEN
                ALTER TABLE mirt_profiles ADD COLUMN commerce JSONB DEFAULT '{}'::JSONB;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'sitniks_chat_id') THEN
                ALTER TABLE mirt_profiles ADD COLUMN sitniks_chat_id TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'last_seen_at') THEN
                ALTER TABLE mirt_profiles ADD COLUMN last_seen_at TIMESTAMPTZ DEFAULT NOW();
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'mirt_profiles' AND column_name = 'completeness_score') THEN
                ALTER TABLE mirt_profiles ADD COLUMN completeness_score FLOAT DEFAULT 0.0;
            END IF;
        ELSE
            RAISE NOTICE '   ⏭️ Skip: mirt_profiles already exists';
        END IF;
    ELSE
        RAISE NOTICE '   ⏭️ No mirt_users found, creating mirt_profiles from scratch...';
    END IF;
END $$;

-- Створюємо mirt_profiles якщо її досі немає
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

-- ============================================================================
-- STEP 7: Створити MIRT_MEMORIES (спрощена версія Titans-like памʼяті)
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 7: Creating MIRT_MEMORIES...';
END $$;

CREATE TABLE IF NOT EXISTS mirt_memories (
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
);

CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_id ON mirt_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_active ON mirt_memories(user_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_mirt_memories_importance ON mirt_memories(importance DESC) WHERE is_active = TRUE;

-- ============================================================================
-- STEP 8: Створити MIRT_MEMORY_SUMMARIES
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '📦 Step 8: Creating MIRT_MEMORY_SUMMARIES...';
END $$;

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
-- STEP 9: Видалити непотрібні таблиці
-- ============================================================================
DO $$ 
BEGIN
    RAISE NOTICE '🗑️ Step 9: Removing unused tables...';
    
    -- Видаляємо mirt_messages (не використовується в коді)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_messages') THEN
        DROP TABLE mirt_messages CASCADE;
        RAISE NOTICE '   ✅ Dropped: mirt_messages (not used in code)';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: mirt_messages does not exist';
    END IF;
    
    -- Видаляємо mirt_users тільки якщо mirt_profiles вже є і mirt_users порожня або була перейменована
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_users') 
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_profiles') THEN
        -- Переносимо дані якщо є
        INSERT INTO mirt_profiles (user_id, created_at, updated_at)
        SELECT user_id, created_at, updated_at 
        FROM mirt_users
        ON CONFLICT (user_id) DO NOTHING;
        
        DROP TABLE mirt_users CASCADE;
        RAISE NOTICE '   ✅ Dropped: mirt_users (migrated to mirt_profiles)';
    ELSE
        RAISE NOTICE '   ⏭️ Skip: mirt_users does not exist or already migrated';
    END IF;
END $$;

-- ============================================================================
-- STEP 10: Автоматичне оновлення updated_at (універсальний тригер)
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Застосовуємо до всіх таблиць з updated_at
DO $$
DECLARE
    tbl TEXT;
BEGIN
    RAISE NOTICE '⚙️ Step 10: Setting up updated_at triggers...';
    
    FOR tbl IN 
        SELECT table_name FROM information_schema.columns 
        WHERE table_schema = 'public' AND column_name = 'updated_at'
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_updated_at ON %I', tbl);
        EXECUTE format('CREATE TRIGGER trg_updated_at BEFORE UPDATE ON %I 
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()', tbl);
    END LOOP;
    
    RAISE NOTICE '   ✅ Triggers created for all tables with updated_at';
END $$;

-- ============================================================================
-- STEP 11: Включити RLS (Row Level Security) для основних таблиць
-- ============================================================================
DO $$
DECLARE
    tbl TEXT;
    tables_to_secure TEXT[] := ARRAY[
        'orders', 'order_items', 'crm_orders', 'sitniks_chat_mappings',
        'mirt_profiles', 'mirt_memories', 'mirt_memory_summaries',
        'users', 'messages', 'llm_usage', 'agent_sessions', 'products',
        'crm_orders', 'sitniks_chat_mappings'
    ];
BEGIN
    RAISE NOTICE '🔒 Step 11: Enabling RLS...';
    
    FOREACH tbl IN ARRAY tables_to_secure LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = tbl) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
            
            -- Створюємо permissive policy для service role
            EXECUTE format('DROP POLICY IF EXISTS "Allow service role" ON %I', tbl);
            EXECUTE format('CREATE POLICY "Allow service role" ON %I FOR ALL USING (true)', tbl);
        END IF;
    END LOOP;
    
    RAISE NOTICE '   ✅ RLS enabled with permissive policies';
END $$;

-- ============================================================================
-- STEP 12: Створити/оновити LLM_USAGE
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_usage (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT,
    model TEXT NOT NULL,
    tokens_input INT NOT NULL DEFAULT 0,
    tokens_output INT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Додати нові колонки якщо таблиця вже існувала
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'session_id') THEN
        ALTER TABLE llm_usage ADD COLUMN session_id TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'latency_ms') THEN
        ALTER TABLE llm_usage ADD COLUMN latency_ms INT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'success') THEN
        ALTER TABLE llm_usage ADD COLUMN success BOOLEAN DEFAULT TRUE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'error_message') THEN
        ALTER TABLE llm_usage ADD COLUMN error_message TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'llm_usage' AND column_name = 'metadata') THEN
        ALTER TABLE llm_usage ADD COLUMN metadata JSONB;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_llm_usage_user_id ON llm_usage(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_usage_session_id ON llm_usage(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at DESC);

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
-- VERIFICATION
-- ============================================================================
DO $$
DECLARE
    table_count INT;
BEGIN
    SELECT COUNT(*) INTO table_count 
    FROM information_schema.tables 
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    
    RAISE NOTICE '';
    RAISE NOTICE '============================================';
    RAISE NOTICE '✅ MIGRATION COMPLETE!';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Total tables in public schema: %', table_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Required tables status:';
    
    -- Check each required table
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'orders') THEN
        RAISE NOTICE '  ✅ orders';
    ELSE
        RAISE NOTICE '  ❌ orders MISSING!';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sitniks_chat_mappings') THEN
        RAISE NOTICE '  ✅ sitniks_chat_mappings';
    ELSE
        RAISE NOTICE '  ❌ sitniks_chat_mappings MISSING!';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_profiles') THEN
        RAISE NOTICE '  ✅ mirt_profiles';
    ELSE
        RAISE NOTICE '  ❌ mirt_profiles MISSING!';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_memories') THEN
        RAISE NOTICE '  ✅ mirt_memories';
    ELSE
        RAISE NOTICE '  ❌ mirt_memories MISSING!';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crm_orders') THEN
        RAISE NOTICE '  ✅ crm_orders';
    ELSE
        RAISE NOTICE '  ❌ crm_orders MISSING!';
    END IF;
    
    -- Check removed tables
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_messages') THEN
        RAISE NOTICE '  ✅ mirt_messages removed';
    ELSE
        RAISE NOTICE '  ⚠️ mirt_messages still exists';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mirt_users') THEN
        RAISE NOTICE '  ✅ mirt_users removed (migrated to mirt_profiles)';
    ELSE
        RAISE NOTICE '  ⚠️ mirt_users still exists';
    END IF;
    
    -- Check new columns
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'orders' AND column_name = 'user_nickname') THEN
        RAISE NOTICE '  ✅ orders.user_nickname';
    ELSE
        RAISE NOTICE '  ❌ orders.user_nickname MISSING!';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'orders' AND column_name = 'sitniks_chat_id') THEN
        RAISE NOTICE '  ✅ orders.sitniks_chat_id';
    ELSE
        RAISE NOTICE '  ❌ orders.sitniks_chat_id MISSING!';
    END IF;
    
    RAISE NOTICE '';
    RAISE NOTICE '============================================';
END $$;

COMMIT;
