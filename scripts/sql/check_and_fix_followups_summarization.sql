-- ============================================================================
-- CHECK AND FIX SCRIPT FOR FOLLOWUPS & SUMMARIZATION
-- ============================================================================
-- Цей скрипт перевіряє та виправляє структуру БД для followups/summarization
-- Запускай поетапно, перевіряючи результати після кожного кроку
-- ============================================================================

-- ============================================================================
-- STEP 1: ПЕРЕВІРКА СТРУКТУРИ ТАБЛИЦЬ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'STEP 1: CHECKING TABLE STRUCTURE';
    RAISE NOTICE '========================================';
END $$;

-- 1.1 Перевірка таблиці users
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '--- Checking USERS table ---';
    
    -- Перевірка user_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'user_id'
    ) THEN
        RAISE NOTICE '✅ users.user_id exists';
    ELSE
        RAISE NOTICE '❌ users.user_id MISSING - will add';
        ALTER TABLE users ADD COLUMN user_id TEXT;
        -- Якщо є id, копіюємо його
        UPDATE users SET user_id = id::TEXT WHERE user_id IS NULL;
        ALTER TABLE users ADD CONSTRAINT users_user_id_key UNIQUE (user_id);
    END IF;
    
    -- Перевірка last_interaction_at
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'last_interaction_at'
    ) THEN
        RAISE NOTICE '✅ users.last_interaction_at exists';
    ELSE
        RAISE NOTICE '❌ users.last_interaction_at MISSING - will add';
        ALTER TABLE users ADD COLUMN last_interaction_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
    
    -- Перевірка tags
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'tags'
    ) THEN
        RAISE NOTICE '✅ users.tags exists';
    ELSE
        RAISE NOTICE '❌ users.tags MISSING - will add';
        ALTER TABLE users ADD COLUMN tags TEXT[] DEFAULT '{}';
    END IF;
END $$;

-- 1.2 Перевірка таблиці messages
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '--- Checking MESSAGES table ---';
    
    -- Перевірка user_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' AND column_name = 'user_id'
    ) THEN
        RAISE NOTICE '✅ messages.user_id exists';
    ELSE
        RAISE NOTICE '❌ messages.user_id MISSING - will add';
        ALTER TABLE messages ADD COLUMN user_id TEXT;
    END IF;
    
    -- Перевірка session_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' AND column_name = 'session_id'
    ) THEN
        RAISE NOTICE '✅ messages.session_id exists';
    ELSE
        RAISE NOTICE '❌ messages.session_id MISSING - CRITICAL!';
    END IF;
    
    -- Перевірка created_at
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' AND column_name = 'created_at'
    ) THEN
        RAISE NOTICE '✅ messages.created_at exists';
    ELSE
        RAISE NOTICE '❌ messages.created_at MISSING - will add';
        ALTER TABLE messages ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END $$;

-- 1.3 Перевірка індексів
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '--- Checking INDEXES ---';
    
    -- Індекси для users
    IF EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'users' AND indexname = 'idx_users_user_id'
    ) THEN
        RAISE NOTICE '✅ idx_users_user_id exists';
    ELSE
        RAISE NOTICE '⚠️ Creating idx_users_user_id';
        CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id) WHERE user_id IS NOT NULL;
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'users' AND indexname = 'idx_users_last_interaction'
    ) THEN
        RAISE NOTICE '✅ idx_users_last_interaction exists';
    ELSE
        RAISE NOTICE '⚠️ Creating idx_users_last_interaction';
        CREATE INDEX IF NOT EXISTS idx_users_last_interaction ON users(last_interaction_at DESC);
    END IF;
    
    -- Індекси для messages
    IF EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'messages' AND indexname = 'idx_messages_user_id'
    ) THEN
        RAISE NOTICE '✅ idx_messages_user_id exists';
    ELSE
        RAISE NOTICE '⚠️ Creating idx_messages_user_id';
        CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id) WHERE user_id IS NOT NULL;
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'messages' AND indexname = 'idx_messages_session_id'
    ) THEN
        RAISE NOTICE '✅ idx_messages_session_id exists';
    ELSE
        RAISE NOTICE '⚠️ Creating idx_messages_session_id';
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'messages' AND indexname = 'idx_messages_created_at'
    ) THEN
        RAISE NOTICE '✅ idx_messages_created_at exists';
    ELSE
        RAISE NOTICE '⚠️ Creating idx_messages_created_at';
        CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at DESC);
    END IF;
END $$;

-- ============================================================================
-- STEP 2: ПЕРЕВІРКА ФУНКЦІЇ summarize_inactive_users
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'STEP 2: CHECKING FUNCTION summarize_inactive_users';
    RAISE NOTICE '========================================';
    
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public' AND p.proname = 'summarize_inactive_users'
    ) THEN
        RAISE NOTICE '✅ Function summarize_inactive_users exists';
    ELSE
        RAISE NOTICE '❌ Function summarize_inactive_users MISSING - creating...';
    END IF;
END $$;

-- Створення функції якщо не існує
CREATE OR REPLACE FUNCTION summarize_inactive_users()
RETURNS TABLE (
    out_user_id TEXT,
    out_username TEXT,
    out_last_interaction_at TIMESTAMPTZ
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
    
    -- Log how many users were marked
    RAISE NOTICE 'summarize_inactive_users: marked % users for summarization', affected_count;
    
    -- Return the affected users
    RETURN QUERY
    SELECT u.user_id, u.username, u.last_interaction_at
    FROM users u
    WHERE COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['needs_summary']::TEXT[]
    ORDER BY u.last_interaction_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION summarize_inactive_users() TO service_role;

-- ============================================================================
-- STEP 3: ПЕРЕВІРКА ДАНИХ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'STEP 3: CHECKING DATA INTEGRITY';
    RAISE NOTICE '========================================';
END $$;

-- 3.1 Перевірка users без user_id
DO $$
DECLARE
    count_no_user_id INT;
BEGIN
    SELECT COUNT(*) INTO count_no_user_id
    FROM users
    WHERE user_id IS NULL OR user_id = '';
    
    IF count_no_user_id > 0 THEN
        RAISE NOTICE '⚠️ Found % users without user_id', count_no_user_id;
        RAISE NOTICE '   Fixing by copying id to user_id...';
        
        UPDATE users
        SET user_id = id::TEXT
        WHERE (user_id IS NULL OR user_id = '') AND id IS NOT NULL;
        
        RAISE NOTICE '   ✅ Fixed';
    ELSE
        RAISE NOTICE '✅ All users have user_id';
    END IF;
END $$;

-- 3.2 Перевірка users без last_interaction_at
DO $$
DECLARE
    count_no_interaction INT;
BEGIN
    SELECT COUNT(*) INTO count_no_interaction
    FROM users
    WHERE last_interaction_at IS NULL;
    
    IF count_no_interaction > 0 THEN
        RAISE NOTICE '⚠️ Found % users without last_interaction_at', count_no_interaction;
        RAISE NOTICE '   Fixing by setting to created_at or NOW()...';
        
        UPDATE users
        SET last_interaction_at = COALESCE(created_at, NOW())
        WHERE last_interaction_at IS NULL;
        
        RAISE NOTICE '   ✅ Fixed';
    ELSE
        RAISE NOTICE '✅ All users have last_interaction_at';
    END IF;
END $$;

-- 3.3 Синхронізація last_interaction_at з messages
DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '--- Syncing last_interaction_at from messages ---';
    
    WITH latest_messages AS (
        SELECT 
            user_id,
            MAX(created_at) as last_msg_time
        FROM messages
        WHERE user_id IS NOT NULL
        GROUP BY user_id
    )
    UPDATE users u
    SET last_interaction_at = lm.last_msg_time
    FROM latest_messages lm
    WHERE u.user_id = lm.user_id
        AND (u.last_interaction_at IS NULL OR u.last_interaction_at < lm.last_msg_time);
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '   ✅ Updated % users with latest message time', updated_count;
END $$;

-- 3.4 Перевірка messages без user_id (але з session_id)
DO $$
DECLARE
    count_no_user_id INT;
BEGIN
    SELECT COUNT(*) INTO count_no_user_id
    FROM messages
    WHERE user_id IS NULL AND session_id IS NOT NULL;
    
    IF count_no_user_id > 0 THEN
        RAISE NOTICE '⚠️ Found % messages without user_id (but with session_id)', count_no_user_id;
        RAISE NOTICE '   Note: These will be skipped in summarization';
    ELSE
        RAISE NOTICE '✅ All messages have user_id or are properly handled';
    END IF;
END $$;

-- ============================================================================
-- STEP 4: СТАТИСТИКА ДЛЯ ПЕРЕВІРКИ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'STEP 4: DATA STATISTICS';
    RAISE NOTICE '========================================';
END $$;

-- 4.1 Статистика users
DO $$
DECLARE
    total_users INT;
    users_with_tags INT;
    users_needing_summary INT;
    inactive_users INT;
BEGIN
    SELECT COUNT(*) INTO total_users FROM users;
    SELECT COUNT(*) INTO users_with_tags FROM users WHERE tags IS NOT NULL AND array_length(tags, 1) > 0;
    SELECT COUNT(*) INTO users_needing_summary FROM users WHERE tags @> ARRAY['needs_summary']::TEXT[];
    SELECT COUNT(*) INTO inactive_users FROM users WHERE last_interaction_at < NOW() - INTERVAL '3 days';
    
    RAISE NOTICE '';
    RAISE NOTICE 'USERS STATISTICS:';
    RAISE NOTICE '  Total users: %', total_users;
    RAISE NOTICE '  Users with tags: %', users_with_tags;
    RAISE NOTICE '  Users needing summary: %', users_needing_summary;
    RAISE NOTICE '  Inactive users (3+ days): %', inactive_users;
END $$;

-- 4.2 Статистика messages
DO $$
DECLARE
    total_messages INT;
    messages_with_user_id INT;
    unique_sessions INT;
    unique_users INT;
BEGIN
    SELECT COUNT(*) INTO total_messages FROM messages;
    SELECT COUNT(*) INTO messages_with_user_id FROM messages WHERE user_id IS NOT NULL;
    SELECT COUNT(DISTINCT session_id) INTO unique_sessions FROM messages;
    SELECT COUNT(DISTINCT user_id) INTO unique_users FROM messages WHERE user_id IS NOT NULL;
    
    RAISE NOTICE '';
    RAISE NOTICE 'MESSAGES STATISTICS:';
    RAISE NOTICE '  Total messages: %', total_messages;
    RAISE NOTICE '  Messages with user_id: %', messages_with_user_id;
    RAISE NOTICE '  Unique sessions: %', unique_sessions;
    RAISE NOTICE '  Unique users: %', unique_users;
END $$;

-- 4.3 Перевірка зв'язків
DO $$
DECLARE
    orphaned_messages INT;
    users_without_messages INT;
BEGIN
    -- Messages з user_id, якого немає в users
    SELECT COUNT(*) INTO orphaned_messages
    FROM messages m
    WHERE m.user_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM users u WHERE u.user_id = m.user_id
        );
    
    -- Users без messages
    SELECT COUNT(*) INTO users_without_messages
    FROM users u
    WHERE NOT EXISTS (
        SELECT 1 FROM messages m WHERE m.user_id = u.user_id
    );
    
    RAISE NOTICE '';
    RAISE NOTICE 'DATA RELATIONSHIPS:';
    RAISE NOTICE '  Orphaned messages (user_id not in users): %', orphaned_messages;
    RAISE NOTICE '  Users without messages: %', users_without_messages;
END $$;

-- ============================================================================
-- STEP 5: ТЕСТОВИЙ ВИКЛИК ФУНКЦІЇ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'STEP 5: TESTING summarize_inactive_users';
    RAISE NOTICE '========================================';
    RAISE NOTICE '';
    RAISE NOTICE 'To test, run: SELECT * FROM summarize_inactive_users();';
    RAISE NOTICE '';
END $$;

-- ============================================================================
-- ФІНАЛЬНИЙ РЕЗЮМЕ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE '✅ CHECK AND FIX COMPLETE!';
    RAISE NOTICE '========================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Review the statistics above';
    RAISE NOTICE '2. Test summarize_inactive_users(): SELECT * FROM summarize_inactive_users();';
    RAISE NOTICE '3. Check followups: Look for sessions with old messages';
    RAISE NOTICE '4. Monitor worker logs for any errors';
    RAISE NOTICE '';
END $$;

