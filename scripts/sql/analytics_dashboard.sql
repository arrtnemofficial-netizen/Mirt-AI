-- =============================================================================
-- MIRT AI ANALYTICS DASHBOARD
-- =============================================================================
-- Run these queries against Supabase to get key metrics.
-- Recommended: Create a Supabase dashboard with these queries.

-- =============================================================================
-- 1. SESSION METRICS
-- =============================================================================

-- 1.1 Sessions by current state (funnel analysis)
SELECT 
    state->>'current_state' as current_state,
    COUNT(*) as session_count,
    ROUND(COUNT(*)::numeric / SUM(COUNT(*)) OVER () * 100, 1) as percentage
FROM mirt_sessions
WHERE updated_at > NOW() - INTERVAL '7 days'
GROUP BY state->>'current_state'
ORDER BY session_count DESC;

-- 1.2 Sessions reaching payment (conversion rate)
SELECT 
    DATE_TRUNC('day', created_at) as day,
    COUNT(*) as total_sessions,
    COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_5_PAYMENT_DELIVERY', 'STATE_6_UPSELL', 'STATE_7_END')) as reached_payment,
    ROUND(
        COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_5_PAYMENT_DELIVERY', 'STATE_6_UPSELL', 'STATE_7_END'))::numeric 
        / NULLIF(COUNT(*), 0) * 100, 1
    ) as conversion_rate
FROM mirt_sessions
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY day DESC;

-- 1.3 Sessions stuck in OFFER (potential issues)
SELECT 
    session_id,
    state->>'current_state' as current_state,
    updated_at,
    NOW() - updated_at as stuck_duration
FROM mirt_sessions
WHERE state->>'current_state' = 'STATE_4_OFFER'
  AND updated_at < NOW() - INTERVAL '1 hour'
ORDER BY stuck_duration DESC
LIMIT 20;

-- =============================================================================
-- 2. INTENT METRICS
-- =============================================================================

-- 2.1 Top intents by frequency
SELECT 
    state->'metadata'->>'intent' as intent,
    COUNT(*) as count,
    ROUND(COUNT(*)::numeric / SUM(COUNT(*)) OVER () * 100, 1) as percentage
FROM mirt_sessions
WHERE updated_at > NOW() - INTERVAL '7 days'
  AND state->'metadata'->>'intent' IS NOT NULL
GROUP BY state->'metadata'->>'intent'
ORDER BY count DESC;

-- 2.2 Intent distribution by state
SELECT 
    state->>'current_state' as current_state,
    state->'metadata'->>'intent' as intent,
    COUNT(*) as count
FROM mirt_sessions
WHERE updated_at > NOW() - INTERVAL '7 days'
GROUP BY state->>'current_state', state->'metadata'->>'intent'
ORDER BY current_state, count DESC;

-- =============================================================================
-- 3. ERROR METRICS
-- =============================================================================

-- 3.1 Sessions with errors
SELECT 
    DATE_TRUNC('hour', updated_at) as hour,
    COUNT(*) FILTER (WHERE state->>'last_error' IS NOT NULL) as error_count,
    COUNT(*) as total_sessions,
    ROUND(
        COUNT(*) FILTER (WHERE state->>'last_error' IS NOT NULL)::numeric 
        / NULLIF(COUNT(*), 0) * 100, 1
    ) as error_rate
FROM mirt_sessions
WHERE updated_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', updated_at)
ORDER BY hour DESC;

-- 3.2 Most common errors
SELECT 
    state->>'last_error' as error,
    COUNT(*) as count
FROM mirt_sessions
WHERE state->>'last_error' IS NOT NULL
  AND updated_at > NOW() - INTERVAL '7 days'
GROUP BY state->>'last_error'
ORDER BY count DESC
LIMIT 10;

-- =============================================================================
-- 4. LLM USAGE (from llm_usage table)
-- =============================================================================

-- 4.1 LLM calls by node
SELECT 
    node_name,
    COUNT(*) as call_count,
    AVG(latency_ms) as avg_latency_ms,
    COUNT(*) FILTER (WHERE status = 'error') as error_count
FROM llm_usage
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY node_name
ORDER BY call_count DESC;

-- 4.2 LLM errors by type
SELECT 
    error_message,
    COUNT(*) as count
FROM llm_usage
WHERE status = 'error'
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY error_message
ORDER BY count DESC
LIMIT 10;

-- =============================================================================
-- 5. PRODUCT METRICS
-- =============================================================================

-- 5.1 Most viewed products (from vision results)
SELECT 
    jsonb_array_elements(state->'selected_products')->>'name' as product_name,
    COUNT(*) as view_count
FROM mirt_sessions
WHERE state->'selected_products' IS NOT NULL
  AND jsonb_array_length(state->'selected_products') > 0
  AND updated_at > NOW() - INTERVAL '30 days'
GROUP BY jsonb_array_elements(state->'selected_products')->>'name'
ORDER BY view_count DESC
LIMIT 20;

-- =============================================================================
-- 6. ESCALATION METRICS
-- =============================================================================

-- 6.1 Escalation rate
SELECT 
    DATE_TRUNC('day', updated_at) as day,
    COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_8_COMPLAINT', 'STATE_9_OOD')) as escalations,
    COUNT(*) as total,
    ROUND(
        COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_8_COMPLAINT', 'STATE_9_OOD'))::numeric 
        / NULLIF(COUNT(*), 0) * 100, 2
    ) as escalation_rate
FROM mirt_sessions
WHERE updated_at > NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', updated_at)
ORDER BY day DESC;

-- =============================================================================
-- 7. ALERT QUERIES (for monitoring)
-- =============================================================================

-- ALERT: High error rate (> 10% in last hour)
SELECT 
    CASE 
        WHEN error_rate > 10 THEN 'ALERT: High error rate!'
        ELSE 'OK'
    END as status,
    error_rate,
    error_count,
    total_sessions
FROM (
    SELECT 
        COUNT(*) FILTER (WHERE state->>'last_error' IS NOT NULL) as error_count,
        COUNT(*) as total_sessions,
        ROUND(
            COUNT(*) FILTER (WHERE state->>'last_error' IS NOT NULL)::numeric 
            / NULLIF(COUNT(*), 0) * 100, 1
        ) as error_rate
    FROM mirt_sessions
    WHERE updated_at > NOW() - INTERVAL '1 hour'
) stats;

-- ALERT: Sessions stuck in OFFER > 1 hour (> 10 sessions)
SELECT 
    CASE 
        WHEN stuck_count > 10 THEN 'ALERT: Many sessions stuck in OFFER!'
        ELSE 'OK'
    END as status,
    stuck_count
FROM (
    SELECT COUNT(*) as stuck_count
    FROM mirt_sessions
    WHERE state->>'current_state' = 'STATE_4_OFFER'
      AND updated_at < NOW() - INTERVAL '1 hour'
) stats;

-- ALERT: Low conversion rate (< 5% today)
SELECT 
    CASE 
        WHEN conversion_rate < 5 THEN 'ALERT: Low conversion rate!'
        ELSE 'OK'
    END as status,
    conversion_rate,
    reached_payment,
    total_sessions
FROM (
    SELECT 
        COUNT(*) as total_sessions,
        COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_5_PAYMENT_DELIVERY', 'STATE_6_UPSELL', 'STATE_7_END')) as reached_payment,
        ROUND(
            COUNT(*) FILTER (WHERE state->>'current_state' IN ('STATE_5_PAYMENT_DELIVERY', 'STATE_6_UPSELL', 'STATE_7_END'))::numeric 
            / NULLIF(COUNT(*), 0) * 100, 1
        ) as conversion_rate
    FROM mirt_sessions
    WHERE created_at > NOW() - INTERVAL '24 hours'
) stats;
