-- ============================================================================
-- MEMORY SYSTEM - SAFE MIGRATION FOR POSTGRESQL
-- ============================================================================
-- Цей скрипт безпечно створює Memory System без конфліктів з існуючою схемою.
-- Виконуй в Supabase SQL Editor.
--
-- ПОРЯДОК ВИКОНАННЯ:
-- 1. Виконай весь файл (Ctrl+Enter)
-- 2. Перевір що немає помилок
-- 3. Готово - Memory System активовано
-- ============================================================================

-- ============================================================================
-- STEP 1: Enable pgvector (if not already enabled)
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- STEP 2: Create mirt_profiles table (Persistent Memory)
-- ============================================================================
-- Це головна таблиця профілів користувачів
-- user_id = Telegram/Instagram/ManyChat ID

CREATE TABLE IF NOT EXISTS mirt_profiles (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT UNIQUE NOT NULL,
    
    -- Child Profile (JSONB for flexibility)
    child_profile JSONB DEFAULT '{}'::JSONB,
    -- Example: {"name": "Марійка", "age": 7, "height_cm": 128, "gender": "дівчинка"}
    
    -- Style Preferences
    style_preferences JSONB DEFAULT '{}'::JSONB,
    -- Example: {"favorite_models": ["Лагуна"], "favorite_colors": ["рожевий"]}
    
    -- Logistics
    logistics JSONB DEFAULT '{}'::JSONB,
    -- Example: {"city": "Харків", "delivery_type": "nova_poshta"}
    
    -- Commerce Behavior
    commerce JSONB DEFAULT '{}'::JSONB,
    -- Example: {"total_orders": 5, "avg_check": 1850}
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    completeness_score FLOAT DEFAULT 0.0
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_mirt_profiles_user_id ON mirt_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_profiles_last_seen ON mirt_profiles(last_seen_at DESC);

-- ============================================================================
-- STEP 3: Create mirt_memories table (Fluid Memory)
-- ============================================================================
-- Атомарні факти про користувача з importance/surprise для gating

CREATE TABLE IF NOT EXISTS mirt_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES mirt_profiles(user_id) ON DELETE CASCADE,
    session_id TEXT,
    
    -- Fact Content
    content TEXT NOT NULL,
    fact_type TEXT NOT NULL,  -- preference, constraint, logistics, behavior, feedback
    category TEXT NOT NULL,   -- child, style, delivery, payment, product, complaint
    
    -- Titans-like Metrics (CRITICAL for gating)
    importance FLOAT NOT NULL DEFAULT 0.5,  -- 0.0-1.0: impact on recommendations
    surprise FLOAT NOT NULL DEFAULT 0.5,    -- 0.0-1.0: novelty of information
    confidence FLOAT NOT NULL DEFAULT 0.8,  -- 0.0-1.0: certainty of fact
    
    -- Time-based decay
    ttl_days INT,                    -- Days until expiry (null = forever)
    decay_rate FLOAT DEFAULT 0.01,   -- Daily importance reduction
    
    -- Vector embedding for semantic search
    embedding VECTOR(1536),  -- Compatible with text-embedding-3-small
    
    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    
    -- Versioning
    version INT DEFAULT 1,
    superseded_by UUID REFERENCES mirt_memories(id),
    is_active BOOLEAN DEFAULT TRUE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_id ON mirt_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_user_active ON mirt_memories(user_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_mirt_memories_type ON mirt_memories(fact_type);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_category ON mirt_memories(category);
CREATE INDEX IF NOT EXISTS idx_mirt_memories_importance ON mirt_memories(importance DESC) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_mirt_memories_expires ON mirt_memories(expires_at) WHERE expires_at IS NOT NULL;

-- Vector similarity search index (HNSW for speed)
CREATE INDEX IF NOT EXISTS idx_mirt_memories_embedding ON mirt_memories 
USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL AND is_active = TRUE;

-- ============================================================================
-- STEP 4: Create mirt_memory_summaries table (Compressed Memory)
-- ============================================================================
-- Стислі summary для зменшення токенів в промпті

CREATE TABLE IF NOT EXISTS mirt_memory_summaries (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id TEXT REFERENCES mirt_profiles(user_id) ON DELETE CASCADE,
    product_id BIGINT,
    session_id TEXT,
    
    summary_type TEXT NOT NULL,  -- user, product, session
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
CREATE INDEX IF NOT EXISTS idx_mirt_summaries_type ON mirt_memory_summaries(summary_type);

-- ============================================================================
-- STEP 5: Create Functions
-- ============================================================================

-- Function: Calculate profile completeness score
CREATE OR REPLACE FUNCTION calculate_profile_completeness(profile_row mirt_profiles)
RETURNS FLOAT AS $$
DECLARE
    score FLOAT := 0.0;
    max_score FLOAT := 0.0;
BEGIN
    -- Child profile (30% weight)
    max_score := max_score + 0.3;
    IF profile_row.child_profile ? 'height_cm' THEN score := score + 0.15; END IF;
    IF profile_row.child_profile ? 'age' THEN score := score + 0.1; END IF;
    IF profile_row.child_profile ? 'gender' THEN score := score + 0.05; END IF;
    
    -- Style preferences (25% weight)
    max_score := max_score + 0.25;
    IF profile_row.style_preferences ? 'favorite_models' THEN score := score + 0.1; END IF;
    IF profile_row.style_preferences ? 'favorite_colors' THEN score := score + 0.1; END IF;
    IF profile_row.style_preferences ? 'preferred_styles' THEN score := score + 0.05; END IF;
    
    -- Logistics (25% weight)
    max_score := max_score + 0.25;
    IF profile_row.logistics ? 'city' THEN score := score + 0.15; END IF;
    IF profile_row.logistics ? 'favorite_branch' THEN score := score + 0.1; END IF;
    
    -- Commerce (20% weight)
    max_score := max_score + 0.2;
    IF profile_row.commerce ? 'total_orders' AND (profile_row.commerce->>'total_orders')::INT > 0 THEN 
        score := score + 0.1; 
    END IF;
    IF profile_row.commerce ? 'payment_preference' THEN score := score + 0.1; END IF;
    
    RETURN ROUND((score / max_score)::NUMERIC, 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Auto-update completeness on profile change
CREATE OR REPLACE FUNCTION update_profile_completeness()
RETURNS TRIGGER AS $$
BEGIN
    NEW.completeness_score := calculate_profile_completeness(NEW);
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for auto-update
DROP TRIGGER IF EXISTS trg_profile_completeness ON mirt_profiles;
CREATE TRIGGER trg_profile_completeness
    BEFORE INSERT OR UPDATE ON mirt_profiles
    FOR EACH ROW EXECUTE FUNCTION update_profile_completeness();

-- Function: Apply time decay to old memories (run daily via cron)
CREATE OR REPLACE FUNCTION apply_memory_decay()
RETURNS INT AS $$
DECLARE
    affected_rows INT;
BEGIN
    -- Reduce importance for old facts
    UPDATE mirt_memories
    SET 
        importance = GREATEST(0.1, importance - decay_rate),
        updated_at = NOW()
    WHERE 
        is_active = TRUE
        AND decay_rate > 0
        AND last_accessed_at < NOW() - INTERVAL '1 day';
    
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    
    -- Deactivate expired facts
    UPDATE mirt_memories
    SET 
        is_active = FALSE,
        updated_at = NOW()
    WHERE 
        is_active = TRUE
        AND expires_at IS NOT NULL
        AND expires_at < NOW();
    
    RETURN affected_rows;
END;
$$ LANGUAGE plpgsql;

-- Function: Semantic memory search
CREATE OR REPLACE FUNCTION search_memories(
    p_user_id TEXT,
    p_query_embedding VECTOR(1536),
    p_limit INT DEFAULT 10,
    p_min_importance FLOAT DEFAULT 0.3,
    p_categories TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    fact_type TEXT,
    category TEXT,
    importance FLOAT,
    surprise FLOAT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.content,
        m.fact_type,
        m.category,
        m.importance,
        m.surprise,
        1 - (m.embedding <=> p_query_embedding) AS similarity
    FROM mirt_memories m
    WHERE 
        m.user_id = p_user_id
        AND m.is_active = TRUE
        AND m.importance >= p_min_importance
        AND (p_categories IS NULL OR m.category = ANY(p_categories))
        AND m.embedding IS NOT NULL
    ORDER BY 
        (1 - (m.embedding <=> p_query_embedding)) * m.importance DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- STEP 6: Enable Row Level Security
-- ============================================================================
ALTER TABLE mirt_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE mirt_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE mirt_memory_summaries ENABLE ROW LEVEL SECURITY;

-- Policies for service role access
DROP POLICY IF EXISTS "Allow all for service role profiles" ON mirt_profiles;
CREATE POLICY "Allow all for service role profiles" ON mirt_profiles FOR ALL USING (TRUE);

DROP POLICY IF EXISTS "Allow all for service role memories" ON mirt_memories;
CREATE POLICY "Allow all for service role memories" ON mirt_memories FOR ALL USING (TRUE);

DROP POLICY IF EXISTS "Allow all for service role summaries" ON mirt_memory_summaries;
CREATE POLICY "Allow all for service role summaries" ON mirt_memory_summaries FOR ALL USING (TRUE);

-- ============================================================================
-- STEP 7: Grant permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION calculate_profile_completeness(mirt_profiles) TO service_role;
GRANT EXECUTE ON FUNCTION update_profile_completeness() TO service_role;
GRANT EXECUTE ON FUNCTION apply_memory_decay() TO service_role;
GRANT EXECUTE ON FUNCTION search_memories(TEXT, VECTOR(1536), INT, FLOAT, TEXT[]) TO service_role;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '✅ MEMORY SYSTEM MIGRATION COMPLETE!';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables created:';
    RAISE NOTICE '  - mirt_profiles (Persistent Memory)';
    RAISE NOTICE '  - mirt_memories (Fluid Memory with vectors)';
    RAISE NOTICE '  - mirt_memory_summaries (Compressed Memory)';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions created:';
    RAISE NOTICE '  - calculate_profile_completeness()';
    RAISE NOTICE '  - apply_memory_decay() - run daily via cron';
    RAISE NOTICE '  - search_memories() - semantic search';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Test: SELECT * FROM mirt_profiles LIMIT 1;';
    RAISE NOTICE '  2. Optional: Set up pg_cron for apply_memory_decay()';
    RAISE NOTICE '';
END $$;
