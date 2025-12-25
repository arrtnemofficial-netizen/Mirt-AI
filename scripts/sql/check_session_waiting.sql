-- =============================================================================
-- ПЕРЕВІРКА СЕСІЙ В СТАНІ ОЧІКУВАННЯ (WAITING_FOR_PAYMENT_PROOF)
-- =============================================================================
-- Ці запити допоможуть перевірити чи правильно працює очікування скріншотів

-- 1. Скільки сесій зараз чекають скріншот оплати?
-- =============================================================================
SELECT 
    COUNT(*) as waiting_count,
    COUNT(*) FILTER (WHERE updated_at < NOW() - INTERVAL '1 hour') as waiting_over_1h,
    COUNT(*) FILTER (WHERE updated_at < NOW() - INTERVAL '6 hours') as waiting_over_6h,
    COUNT(*) FILTER (WHERE updated_at < NOW() - INTERVAL '24 hours') as waiting_over_24h
FROM agent_sessions
WHERE state->>'dialog_phase' = 'WAITING_FOR_PAYMENT_PROOF'
  AND state->>'current_state' = 'STATE_5_PAYMENT_DELIVERY';

-- 2. Детальний список сесій що чекають скріншот (з часом очікування)
-- =============================================================================
SELECT 
    session_id,
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    state->'metadata'->>'customer_name' as customer_name,
    state->'metadata'->>'customer_phone' as customer_phone,
    state->'metadata'->>'payment_details_sent' as payment_details_sent,
    updated_at,
    NOW() - updated_at as waiting_duration,
    EXTRACT(EPOCH FROM (NOW() - updated_at)) / 60 as waiting_minutes
FROM agent_sessions
WHERE state->>'dialog_phase' = 'WAITING_FOR_PAYMENT_PROOF'
  AND state->>'current_state' = 'STATE_5_PAYMENT_DELIVERY'
ORDER BY updated_at ASC
LIMIT 50;

-- 3. Перевірка vision_greeted (чи правильно зберігається)
-- =============================================================================
SELECT 
    session_id,
    state->'metadata'->>'vision_greeted' as vision_greeted,
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    updated_at,
    -- Перевірка чи є привітання в історії повідомлень
    (
        SELECT COUNT(*) > 0
        FROM jsonb_array_elements(state->'messages') as msg
        WHERE msg->>'role' = 'assistant'
          AND LOWER(msg->>'content') LIKE '%менеджер соф%'
    ) as has_greeting_in_history
FROM agent_sessions
WHERE state->>'current_state' != 'STATE_0_INIT'  -- Активні сесії (не нові)
ORDER BY updated_at DESC
LIMIT 20;

-- 4. Сесії які можуть бути "застрягли" (неактивні довго)
-- =============================================================================
SELECT 
    session_id,
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    updated_at,
    NOW() - updated_at as inactive_duration,
    CASE 
        WHEN state->>'current_state' = 'STATE_5_PAYMENT_DELIVERY' 
             AND state->>'dialog_phase' = 'WAITING_FOR_PAYMENT_PROOF' 
        THEN 'Чекає скріншот'
        WHEN state->>'current_state' = 'STATE_4_OFFER' 
             AND state->>'dialog_phase' = 'OFFER_MADE' 
        THEN 'Чекає згоду'
        WHEN state->>'current_state' = 'STATE_5_PAYMENT_DELIVERY' 
             AND state->>'dialog_phase' = 'WAITING_FOR_DELIVERY_DATA' 
        THEN 'Чекає дані доставки'
        ELSE 'Інший стан'
    END as waiting_for,
    state->'metadata'->>'customer_name' as customer_name
FROM agent_sessions
WHERE updated_at < NOW() - INTERVAL '1 hour'  -- Неактивні більше 1 години
  AND state->>'current_state' NOT IN ('STATE_7_END', 'STATE_0_INIT')  -- Не завершені
ORDER BY updated_at ASC
LIMIT 30;

-- 5. Статистика по станах (скільки сесій в кожному стані)
-- =============================================================================
SELECT 
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    COUNT(*) as session_count,
    MIN(updated_at) as oldest_session,
    MAX(updated_at) as newest_session,
    AVG(EXTRACT(EPOCH FROM (NOW() - updated_at)) / 60) as avg_waiting_minutes
FROM agent_sessions
WHERE state->>'current_state' IS NOT NULL
GROUP BY state->>'current_state', state->>'dialog_phase'
ORDER BY session_count DESC;

-- 6. Перевірка чи правильно зберігається payment_details_sent
-- =============================================================================
SELECT 
    session_id,
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    state->'metadata'->>'payment_details_sent' as payment_details_sent,
    state->'metadata'->>'payment_proof_received' as payment_proof_received,
    updated_at
FROM agent_sessions
WHERE state->>'current_state' = 'STATE_5_PAYMENT_DELIVERY'
  AND (
    state->>'dialog_phase' = 'WAITING_FOR_PAYMENT_PROOF'
    OR state->'metadata'->>'payment_details_sent' = 'true'
  )
ORDER BY updated_at DESC
LIMIT 20;

-- 7. Сесії які можливо "забули" (дуже старі, але не COMPLETED)
-- =============================================================================
SELECT 
    session_id,
    state->>'current_state' as current_state,
    state->>'dialog_phase' as dialog_phase,
    created_at,
    updated_at,
    NOW() - updated_at as age,
    state->'metadata'->>'customer_name' as customer_name
FROM agent_sessions
WHERE updated_at < NOW() - INTERVAL '7 days'  -- Старіше 7 днів
  AND state->>'current_state' != 'STATE_7_END'  -- Не завершені
ORDER BY updated_at ASC
LIMIT 50;

-- 8. Перевірка чи є сесії без vision_greeted (можлива проблема)
-- =============================================================================
SELECT 
    session_id,
    state->'metadata'->>'vision_greeted' as vision_greeted,
    state->>'current_state' as current_state,
    (
        SELECT COUNT(*) > 0
        FROM jsonb_array_elements(state->'messages') as msg
        WHERE msg->>'role' = 'assistant'
          AND LOWER(msg->>'content') LIKE '%менеджер соф%'
    ) as has_greeting_in_messages,
    updated_at
FROM agent_sessions
WHERE state->>'current_state' != 'STATE_0_INIT'
  AND (
    state->'metadata'->>'vision_greeted' IS NULL
    OR state->'metadata'->>'vision_greeted' = 'false'
  )
ORDER BY updated_at DESC
LIMIT 20;

