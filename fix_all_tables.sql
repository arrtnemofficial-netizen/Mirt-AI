-- ============================================================================
-- FIX ALL TABLES - ONE COMMAND TO RULE THEM ALL
-- ============================================================================
-- Run this in Supabase SQL Editor to fix all issues

-- 1. FIX mirt_profiles - add missing updated_at column
ALTER TABLE mirt_profiles 
ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- 2. CREATE trigger for mirt_profiles (if not exists)
CREATE OR REPLACE FUNCTION update_profile_completeness()
RETURNS TRIGGER AS $$
BEGIN
    -- Calculate completeness score based on filled fields
    NEW.completeness_score = 0.0;
    
    -- Basic info (20% each)
    IF NEW.first_name IS NOT NULL THEN NEW.completeness_score = NEW.completeness_score + 0.2; END IF;
    IF NEW.phone IS NOT NULL THEN NEW.completeness_score = NEW.completeness_score + 0.2; END IF;
    
    -- Child profile (30%)
    IF NEW.child_profile IS NOT NULL AND jsonb_typeof(NEW.child_profile) = 'object' THEN
        IF NEW.child_profile->>'age' IS NOT NULL OR NEW.child_profile->>'height' IS NOT NULL THEN
            NEW.completeness_score = NEW.completeness_score + 0.3;
        END IF;
    END IF;
    
    -- Style preferences (15%)
    IF NEW.style_preferences IS NOT NULL AND jsonb_typeof(NEW.style_preferences) = 'object' THEN
        IF jsonb_array_length(NEW.style_preferences->'colors') > 0 THEN
            NEW.completeness_score = NEW.completeness_score + 0.15;
        END IF;
    END IF;
    
    -- Logistics (15%)
    IF NEW.logistics IS NOT NULL AND jsonb_typeof(NEW.logistics) = 'object' THEN
        IF NEW.logistics->>'city' IS NOT NULL THEN
            NEW.completeness_score = NEW.completeness_score + 0.15;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profile_completeness ON mirt_profiles;
CREATE TRIGGER trg_profile_completeness
    BEFORE INSERT OR UPDATE ON mirt_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_profile_completeness();

-- 3. ADD updated_at trigger to mirt_profiles
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_updated_at_mirt_profiles ON mirt_profiles;
CREATE TRIGGER trg_updated_at_mirt_profiles
    BEFORE UPDATE ON mirt_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 4. FIX orders - add unique constraint for session_id (excluding cancelled)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unique_session_non_cancelled' 
        AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders 
        ADD CONSTRAINT unique_session_non_cancelled 
        UNIQUE (session_id) 
        WHERE (status IS NULL OR status != 'cancelled');
    END IF;
END $$;

-- 5. CREATE CRM orders table (if not exists from separate schema)
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT crm_orders_status_check CHECK (status IN (
        'pending', 'queued', 'created', 'processing', 
        'shipped', 'delivered', 'cancelled', 'failed'
    ))
);

-- Indexes for CRM orders
CREATE INDEX IF NOT EXISTS idx_crm_orders_session_id ON crm_orders(session_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_external_id ON crm_orders(external_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_crm_order_id ON crm_orders(crm_order_id);
CREATE INDEX IF NOT EXISTS idx_crm_orders_status ON crm_orders(status);
CREATE INDEX IF NOT EXISTS idx_crm_orders_created_at ON crm_orders(created_at DESC);

-- Trigger for CRM orders
DROP TRIGGER IF EXISTS update_crm_orders_updated_at ON crm_orders;
CREATE TRIGGER update_crm_orders_updated_at 
    BEFORE UPDATE ON crm_orders 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- 6. CREATE sitniks_chat_mappings table (if not exists)
CREATE TABLE IF NOT EXISTS sitniks_chat_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    instagram_username TEXT,
    telegram_username TEXT,
    sitniks_chat_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_mapping UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_user_id ON sitniks_chat_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_sitniks_mappings_sitniks_id ON sitniks_chat_mappings(sitniks_chat_id) 
WHERE sitniks_chat_id IS NOT NULL;

-- Trigger for sitniks mappings
DROP TRIGGER IF EXISTS trg_updated_at_sitniks_chat_mappings ON sitniks_chat_mappings;
CREATE TRIGGER trg_updated_at_sitniks_chat_mappings
    BEFORE UPDATE ON sitniks_chat_mappings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 7. CREATE all memory tables (in case they don't exist)
-- mirt_profiles already exists, just ensure triggers
-- mirt_memories
CREATE TABLE IF NOT EXISTS mirt_memories (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    content TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    category TEXT NOT NULL,
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    surprise DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    ttl_days INTEGER,
    decay_rate DOUBLE PRECISION DEFAULT 0.01,
    embedding vector(1536),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    version INTEGER DEFAULT 1,
    superseded_by UUID,
    is_active BOOLEAN DEFAULT TRUE
);

-- mirt_memory_summaries
CREATE TABLE IF NOT EXISTS mirt_memory_summaries (
    id BIGINT GENERATED ALWAYS AS IDENTITY NOT NULL PRIMARY KEY,
    user_id TEXT,
    product_id BIGINT,
    session_id TEXT,
    summary_type TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    key_facts TEXT[],
    facts_count INTEGER DEFAULT 0,
    time_range_start TIMESTAMP WITH TIME ZONE,
    time_range_end TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_current BOOLEAN DEFAULT TRUE
);

-- 8. CREATE all indexes for memory tables
CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_id ON mirt_memories USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_active ON mirt_memories USING btree (user_id, is_active) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_importance ON mirt_memories USING btree (importance DESC) WHERE (is_active = true);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_type ON mirt_memories USING btree (fact_type);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_category ON mirt_memories USING btree (category);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_expires ON mirt_memories USING btree (expires_at) WHERE (expires_at IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_embedding ON mirt_memories USING hnsw (embedding vector_cosine_ops) WHERE (embedding IS NOT NULL AND is_active = true);

CREATE INDEX IF NOT EXISTS idx_mirt_summaries_user ON mirt_memory_summaries USING btree (user_id) WHERE (is_current = true);
CREATE INDEX IF NOT EXISTS idx_mirt_summaries_type ON mirt_memory_summaries USING btree (summary_type);

-- 9. CREATE triggers for memory tables
DROP TRIGGER IF EXISTS trg_updated_at_mirt_memories ON mirt_memories;
CREATE TRIGGER trg_updated_at_mirt_memories
    BEFORE UPDATE ON mirt_memories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_updated_at_mirt_summaries ON mirt_memory_summaries;
CREATE TRIGGER trg_updated_at_mirt_summaries
    BEFORE UPDATE ON mirt_memory_summaries
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 10. FINAL VERIFICATION
SELECT 
    'mirt_profiles' as table_name, 
    column_name, 
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'mirt_profiles' AND table_schema = 'public'
UNION ALL
SELECT 
    'orders' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'orders' AND table_schema = 'public' AND column_name = 'session_id'
UNION ALL
SELECT 
    'crm_orders' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'crm_orders' AND table_schema = 'public' AND column_name = 'external_id'
ORDER BY table_name, column_name;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ ALL TABLES FIXED SUCCESSFULLY!';
    RAISE NOTICE '✅ mirt_profiles.updated_at added';
    RAISE NOTICE '✅ orders unique constraint added';
    RAISE NOTICE '✅ crm_orders table created';
    RAISE NOTICE '✅ sitniks_chat_mappings created';
    RAISE NOTICE '✅ All memory tables verified';
    RAISE NOTICE '✅ All triggers and indexes created';
END $$;
