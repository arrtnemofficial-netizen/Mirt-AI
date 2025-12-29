-- ============================================================================
-- MIGRATION: Add TTL filter to search_memories function
-- ============================================================================
-- Issue: search_memories() returns expired facts (where expires_at < NOW())
-- Fix: Add expires_at filter to enforce TTL without requiring cleanup cron
-- ============================================================================

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
        -- TTL enforcement: filter expired facts even if cleanup hasn't run
        AND (m.expires_at IS NULL OR m.expires_at > NOW())
    ORDER BY 
        (1 - (m.embedding <=> p_query_embedding)) * m.importance DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- Verify the change
DO $$
BEGIN
    RAISE NOTICE '✅ search_memories() updated with TTL filter';
END $$;
