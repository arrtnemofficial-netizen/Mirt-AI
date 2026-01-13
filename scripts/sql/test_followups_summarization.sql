-- ============================================================================
-- TEST QUERIES FOR FOLLOWUPS & SUMMARIZATION
-- ============================================================================
-- Ці запити допоможуть перевірити, чи правильно працюють followups/summarization
-- ============================================================================

-- ============================================================================
-- 1. ПЕРЕВІРКА USERS ДЛЯ SUMMARIZATION
-- ============================================================================

-- 1.1 Користувачі, які потребують summarization (3+ дні неактивності)
SELECT 
    user_id,
    username,
    last_interaction_at,
    tags,
    NOW() - last_interaction_at AS days_inactive,
    CASE 
        WHEN tags @> ARRAY['needs_summary']::TEXT[] THEN '✅ Marked'
        WHEN tags @> ARRAY['summarized']::TEXT[] THEN '✅ Summarized'
        ELSE '⏳ Pending'
    END AS status
FROM users
WHERE last_interaction_at < NOW() - INTERVAL '3 days'
ORDER BY last_interaction_at ASC
LIMIT 20;

-- 1.2 Тест функції summarize_inactive_users
SELECT * FROM summarize_inactive_users();

-- 1.3 Користувачі з тегом needs_summary
SELECT 
    user_id,
    username,
    last_interaction_at,
    tags
FROM users
WHERE tags @> ARRAY['needs_summary']::TEXT[]
ORDER BY last_interaction_at ASC;

-- ============================================================================
-- 2. ПЕРЕВІРКА MESSAGES ДЛЯ FOLLOWUPS
-- ============================================================================

-- 2.1 Сесії з останнім повідомленням старше 1 години (для тестування followups)
SELECT 
    m.session_id,
    m.user_id,
    MAX(m.created_at) AS last_message_at,
    NOW() - MAX(m.created_at) AS time_since_last_message,
    COUNT(*) AS message_count
FROM messages m
WHERE m.user_id IS NOT NULL
GROUP BY m.session_id, m.user_id
HAVING MAX(m.created_at) < NOW() - INTERVAL '1 hour'
ORDER BY MAX(m.created_at) ASC
LIMIT 20;

-- 2.2 Сесії з останнім повідомленням старше 24 годин (для реальних followups)
SELECT 
    m.session_id,
    m.user_id,
    MAX(m.created_at) AS last_message_at,
    NOW() - MAX(m.created_at) AS time_since_last_message,
    COUNT(*) AS message_count,
    -- Перевірка чи є followup теги
    EXISTS (
        SELECT 1 FROM messages m2 
        WHERE m2.session_id = m.session_id 
        AND m2.tags && ARRAY['followup-sent-1', 'followup-sent-2', 'followup-sent-3']::TEXT[]
    ) AS has_followup_tags
FROM messages m
WHERE m.user_id IS NOT NULL
GROUP BY m.session_id, m.user_id
HAVING MAX(m.created_at) < NOW() - INTERVAL '24 hours'
ORDER BY MAX(m.created_at) ASC
LIMIT 20;

-- 2.3 Повідомлення з followup тегами
SELECT 
    session_id,
    user_id,
    role,
    content,
    tags,
    created_at
FROM messages
WHERE tags && ARRAY['followup-sent-1', 'followup-sent-2', 'followup-sent-3']::TEXT[]
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================================
-- 3. ПЕРЕВІРКА ЗВ'ЯЗКІВ МІЖ ТАБЛИЦЯМИ
-- ============================================================================

-- 3.1 Користувачі з messages та їх остання активність
SELECT 
    u.user_id,
    u.username,
    u.last_interaction_at AS user_last_interaction,
    MAX(m.created_at) AS last_message_time,
    COUNT(m.id) AS message_count,
    COUNT(DISTINCT m.session_id) AS session_count
FROM users u
LEFT JOIN messages m ON u.user_id = m.user_id
GROUP BY u.user_id, u.username, u.last_interaction_at
ORDER BY u.last_interaction_at DESC NULLS LAST
LIMIT 20;

-- 3.2 Сесії без user_id (можуть бути проблемою)
SELECT 
    session_id,
    COUNT(*) AS message_count,
    MIN(created_at) AS first_message,
    MAX(created_at) AS last_message
FROM messages
WHERE user_id IS NULL
GROUP BY session_id
ORDER BY MAX(created_at) DESC
LIMIT 20;

-- ============================================================================
-- 4. СИМУЛЯЦІЯ РОБОТИ WORKER'ІВ
-- ============================================================================

-- 4.1 Які користувачі будуть оброблені summarization worker'ом
WITH inactive_users AS (
    SELECT 
        u.user_id,
        u.username,
        u.last_interaction_at,
        u.tags
    FROM users u
    WHERE 
        u.last_interaction_at < NOW() - INTERVAL '3 days'
        AND NOT (COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['needs_summary']::TEXT[])
        AND NOT (COALESCE(u.tags, ARRAY[]::TEXT[]) @> ARRAY['summarized']::TEXT[])
)
SELECT 
    iu.*,
    COUNT(m.id) AS message_count,
    MAX(m.created_at) AS last_message_time
FROM inactive_users iu
LEFT JOIN messages m ON iu.user_id = m.user_id
GROUP BY iu.user_id, iu.username, iu.last_interaction_at, iu.tags
ORDER BY iu.last_interaction_at ASC
LIMIT 20;

-- 4.2 Які сесії будуть оброблені followups worker'ом (через 24 години)
SELECT 
    m.session_id,
    m.user_id,
    MAX(m.created_at) AS last_message_at,
    NOW() - MAX(m.created_at) AS hours_since_last_message,
    COUNT(*) AS total_messages,
    -- Скільки followups вже відправлено
    (
        SELECT COUNT(*) 
        FROM messages m2 
        WHERE m2.session_id = m.session_id 
        AND m2.tags && ARRAY['followup-sent-1', 'followup-sent-2', 'followup-sent-3']::TEXT[]
    ) AS followups_sent
FROM messages m
WHERE m.user_id IS NOT NULL
GROUP BY m.session_id, m.user_id
HAVING MAX(m.created_at) < NOW() - INTERVAL '24 hours'
ORDER BY MAX(m.created_at) ASC
LIMIT 20;

-- ============================================================================
-- 5. ДІАГНОСТИКА ПРОБЛЕМ
-- ============================================================================

-- 5.1 Користувачі з невідповідністю last_interaction_at
SELECT 
    u.user_id,
    u.last_interaction_at AS user_last_interaction,
    MAX(m.created_at) AS actual_last_message,
    u.last_interaction_at - MAX(m.created_at) AS discrepancy
FROM users u
JOIN messages m ON u.user_id = m.user_id
GROUP BY u.user_id, u.last_interaction_at
HAVING ABS(EXTRACT(EPOCH FROM (u.last_interaction_at - MAX(m.created_at)))) > 3600  -- більше 1 години різниці
ORDER BY ABS(EXTRACT(EPOCH FROM (u.last_interaction_at - MAX(m.created_at)))) DESC
LIMIT 20;

-- 5.2 Дублікати user_id в users (не повинно бути через UNIQUE constraint)
SELECT 
    user_id,
    COUNT(*) AS count
FROM users
GROUP BY user_id
HAVING COUNT(*) > 1;

-- 5.3 Сесії з багатьма user_id (може бути проблемою)
SELECT 
    session_id,
    COUNT(DISTINCT user_id) AS unique_user_count,
    array_agg(DISTINCT user_id) AS user_ids
FROM messages
WHERE user_id IS NOT NULL
GROUP BY session_id
HAVING COUNT(DISTINCT user_id) > 1
LIMIT 20;

-- ============================================================================
-- 6. МАНУАЛЬНІ ТЕСТИ
-- ============================================================================

-- 6.1 Створити тестового користувача для summarization
-- INSERT INTO users (user_id, username, last_interaction_at, tags)
-- VALUES ('test_summarization_user', 'test_user', NOW() - INTERVAL '4 days', ARRAY[]::TEXT[])
-- ON CONFLICT (user_id) DO UPDATE SET last_interaction_at = NOW() - INTERVAL '4 days';

-- 6.2 Створити тестові messages для followups
-- INSERT INTO messages (session_id, user_id, role, content, created_at)
-- VALUES 
--     ('test_followup_session', 'test_followup_user', 'user', 'Test message', NOW() - INTERVAL '25 hours'),
--     ('test_followup_session', 'test_followup_user', 'assistant', 'Test response', NOW() - INTERVAL '25 hours')
-- ON CONFLICT DO NOTHING;

-- 6.3 Очистити тестові дані
-- DELETE FROM messages WHERE session_id = 'test_followup_session';
-- DELETE FROM users WHERE user_id IN ('test_summarization_user', 'test_followup_user');

