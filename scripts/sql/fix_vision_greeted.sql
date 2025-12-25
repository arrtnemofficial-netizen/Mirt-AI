-- =============================================================================
-- ВИПРАВЛЕННЯ vision_greeted ДЛЯ СТАРИХ СЕСІЙ
-- =============================================================================
-- Оновлює vision_greeted = true для сесій які мають привітання в історії,
-- але vision_greeted = null або false

-- 1. Перевірка скільки сесій потребують виправлення
-- =============================================================================
SELECT 
    COUNT(*) as needs_fix_count
FROM agent_sessions
WHERE (
    state->'metadata'->>'vision_greeted' IS NULL
    OR state->'metadata'->>'vision_greeted' = 'false'
)
AND (
    -- Перевірка чи є привітання в історії повідомлень
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(state->'messages') as msg
        WHERE msg->>'role' = 'assistant'
          AND (
            LOWER(msg->>'content') LIKE '%менеджер соф%'
            OR (LOWER(msg->>'content') LIKE '%вітаю%' AND LOWER(msg->>'content') LIKE '%mirt%')
          )
    )
);

-- 2. Оновлення vision_greeted для сесій з привітанням в історії
-- =============================================================================
UPDATE agent_sessions
SET state = jsonb_set(
    state,
    '{metadata,vision_greeted}',
    'true'::jsonb,
    true  -- create if missing
)
WHERE (
    state->'metadata'->>'vision_greeted' IS NULL
    OR state->'metadata'->>'vision_greeted' = 'false'
)
AND (
    -- Перевірка чи є привітання в історії повідомлень
    EXISTS (
        SELECT 1
        FROM jsonb_array_elements(state->'messages') as msg
        WHERE msg->>'role' = 'assistant'
          AND (
            LOWER(msg->>'content') LIKE '%менеджер соф%'
            OR (LOWER(msg->>'content') LIKE '%вітаю%' AND LOWER(msg->>'content') LIKE '%mirt%')
          )
    )
);

-- 3. Перевірка результатів (після оновлення)
-- =============================================================================
SELECT 
    COUNT(*) as fixed_count,
    COUNT(*) FILTER (WHERE state->'metadata'->>'vision_greeted' = 'true') as now_true,
    COUNT(*) FILTER (WHERE state->'metadata'->>'vision_greeted' IS NULL) as still_null
FROM agent_sessions
WHERE state->>'current_state' != 'STATE_0_INIT';

-- 4. Детальний список виправлених сесій
-- =============================================================================
SELECT 
    session_id,
    state->>'current_state' as current_state,
    state->'metadata'->>'vision_greeted' as vision_greeted,
    updated_at
FROM agent_sessions
WHERE state->'metadata'->>'vision_greeted' = 'true'
  AND updated_at > NOW() - INTERVAL '1 hour'  -- Нещодавно оновлені
ORDER BY updated_at DESC
LIMIT 20;

