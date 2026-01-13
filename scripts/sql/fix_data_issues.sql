-- ============================================================================
-- FIX DATA ISSUES FOR FOLLOWUPS & SUMMARIZATION
-- ============================================================================
-- Цей скрипт виправляє конкретні проблеми з даними
-- ВАЖЛИВО: Запускай тільки після перевірки через check_and_fix_followups_summarization.sql
-- ============================================================================

-- ============================================================================
-- FIX 1: СИНХРОНІЗАЦІЯ last_interaction_at З MESSAGES
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE 'FIX 1: Syncing last_interaction_at from messages...';
    
    WITH latest_messages AS (
        SELECT 
            user_id,
            MAX(created_at) as last_msg_time
        FROM messages
        WHERE user_id IS NOT NULL
        GROUP BY user_id
    )
    UPDATE users u
    SET 
        last_interaction_at = lm.last_msg_time,
        updated_at = NOW()
    FROM latest_messages lm
    WHERE u.user_id = lm.user_id
        AND (u.last_interaction_at IS NULL OR u.last_interaction_at < lm.last_msg_time);
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % users', updated_count;
END $$;

-- ============================================================================
-- FIX 2: ЗАПОВНЕННЯ user_id В MESSAGES З USERS (якщо можливо)
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 2: Filling user_id in messages from users table...';
    
    -- Якщо session_id = user_id (для Telegram/ManyChat)
    UPDATE messages m
    SET user_id = u.user_id
    FROM users u
    WHERE m.user_id IS NULL
        AND m.session_id = u.user_id;
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % messages', updated_count;
END $$;

-- ============================================================================
-- FIX 3: ОНОВЛЕННЯ tags ДЛЯ КОРИСТУВАЧІВ БЕЗ ТЕГІВ
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 3: Initializing tags for users without tags...';
    
    UPDATE users
    SET tags = ARRAY[]::TEXT[]
    WHERE tags IS NULL;
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % users', updated_count;
END $$;

-- ============================================================================
-- FIX 4: ВИДАЛЕННЯ ДУБЛІКАТІВ needs_summary ТЕГУ
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 4: Removing duplicate needs_summary tags...';
    
    UPDATE users
    SET tags = ARRAY(SELECT DISTINCT unnest(tags))
    WHERE tags @> ARRAY['needs_summary']::TEXT[]
        AND array_length(tags, 1) > array_length(ARRAY(SELECT DISTINCT unnest(tags)), 1);
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % users', updated_count;
END $$;

-- ============================================================================
-- FIX 5: ОНОВЛЕННЯ created_at ДЛЯ MESSAGES БЕЗ created_at
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 5: Setting created_at for messages without it...';
    
    UPDATE messages
    SET created_at = NOW()
    WHERE created_at IS NULL;
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % messages', updated_count;
END $$;

-- ============================================================================
-- FIX 6: СТВОРЕННЯ USERS ДЛЯ MESSAGES БЕЗ USER_ID (якщо session_id = user_id)
-- ============================================================================

DO $$
DECLARE
    created_count INT := 0;
    updated_count INT;
    session_rec RECORD;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 6: Creating users for messages with session_id but no user_id...';
    
    -- Створюємо users для messages без user_id по одному (щоб уникнути проблем з id)
    FOR session_rec IN
        SELECT DISTINCT
            m.session_id AS session_id,
            MAX(m.created_at) AS last_interaction_at,
            MIN(m.created_at) AS first_message_at
        FROM messages m
        WHERE m.user_id IS NULL
            AND m.session_id IS NOT NULL
            AND m.session_id != ''
            AND NOT EXISTS (
                SELECT 1 FROM users u WHERE u.user_id = m.session_id
            )
        GROUP BY m.session_id
    LOOP
        BEGIN
            INSERT INTO users (user_id, username, last_interaction_at, tags, created_at, updated_at)
            VALUES (
                session_rec.session_id,
                NULL::TEXT,
                session_rec.last_interaction_at,
                '{}'::TEXT[],
                COALESCE(session_rec.first_message_at, NOW()),
                COALESCE(session_rec.last_interaction_at, NOW())
            )
            ON CONFLICT (user_id) DO NOTHING;
            
            created_count := created_count + 1;
        EXCEPTION
            WHEN OTHERS THEN
                RAISE NOTICE '⚠️ Failed to create user for session_id %: %', session_rec.session_id, SQLERRM;
        END;
    END LOOP;
    
    RAISE NOTICE '✅ Created % users', created_count;
    
    -- Тепер оновлюємо messages з цими user_id
    UPDATE messages m
    SET user_id = m.session_id
    WHERE m.user_id IS NULL
        AND m.session_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM users u WHERE u.user_id = m.session_id
        );
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % messages with user_id', updated_count;
END $$;

-- ============================================================================
-- FIX 7: ОЧИСТКА СТАРИХ ТЕГІВ needs_summary ДЛЯ ВЖЕ SUMMARIZED КОРИСТУВАЧІВ
-- ============================================================================

DO $$
DECLARE
    updated_count INT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE 'FIX 7: Cleaning up needs_summary tags for already summarized users...';
    
    UPDATE users
    SET tags = array_remove(tags, 'needs_summary')
    WHERE tags @> ARRAY['summarized']::TEXT[]
        AND tags @> ARRAY['needs_summary']::TEXT[];
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Updated % users', updated_count;
END $$;

-- ============================================================================
-- ФІНАЛЬНА ПЕРЕВІРКА
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE '✅ ALL FIXES APPLIED!';
    RAISE NOTICE '========================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Run test_followups_summarization.sql to verify';
    RAISE NOTICE '';
END $$;

