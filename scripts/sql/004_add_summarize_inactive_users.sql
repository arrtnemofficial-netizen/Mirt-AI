-- ============================================================================
-- MIGRATION: Add summarize_inactive_users function
-- ============================================================================
-- This function marks users as needing summary after 3 days of inactivity.
-- Called by Python worker: client.rpc("summarize_inactive_users")
--
-- IMPORTANT: Uses new table names:
--   - users (NOT mirt_users)
--   - messages (NOT mirt_messages)
-- ============================================================================

-- Drop old function if exists (might be pointing to wrong tables)
DROP FUNCTION IF EXISTS summarize_inactive_users();

-- Create new function using correct table names
CREATE OR REPLACE FUNCTION summarize_inactive_users()
RETURNS TABLE (
    user_id TEXT,
    username TEXT,
    last_interaction_at TIMESTAMPTZ
) AS $$
DECLARE
    affected_count INT := 0;
BEGIN
    -- Find users inactive for 3+ days who don't already have 'needs_summary' tag
    -- and are not already 'summarized'
    WITH inactive_users AS (
        SELECT u.user_id, u.username, u.last_interaction_at, u.tags
        FROM users u
        WHERE 
            u.last_interaction_at < NOW() - INTERVAL '3 days'
            AND NOT (u.tags @> ARRAY['needs_summary']::TEXT[])
            AND NOT (u.tags @> ARRAY['summarized']::TEXT[])
    ),
    updated AS (
        UPDATE users
        SET 
            tags = array_append(
                COALESCE(tags, ARRAY[]::TEXT[]),
                'needs_summary'
            ),
            updated_at = NOW()
        FROM inactive_users iu
        WHERE users.user_id = iu.user_id
        RETURNING users.user_id, users.username, users.last_interaction_at
    )
    SELECT COUNT(*) INTO affected_count FROM updated;
    
    -- Log how many users were marked
    RAISE NOTICE 'summarize_inactive_users: marked % users for summarization', affected_count;
    
    -- Return the affected users
    RETURN QUERY
    SELECT u.user_id, u.username, u.last_interaction_at
    FROM users u
    WHERE u.tags @> ARRAY['needs_summary']::TEXT[]
    ORDER BY u.last_interaction_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Grant execute permission to service role
GRANT EXECUTE ON FUNCTION summarize_inactive_users() TO service_role;

-- ============================================================================
-- VERIFICATION: Run this to test
-- ============================================================================
-- SELECT * FROM summarize_inactive_users();
