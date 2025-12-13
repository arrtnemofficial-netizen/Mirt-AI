-- ============================================================================
-- MIRT AI - Supabase Table Tests: MEMORY SYSTEM (Titans-like)
-- ============================================================================
-- Run in Supabase SQL Editor
-- Tests: mirt_profiles, mirt_memories, mirt_memory_summaries
-- ============================================================================

-- ============================================================================
-- TEST SUITE 7: MIRT_PROFILES (Persistent Memory)
-- ============================================================================

-- TEST 7.1: Insert test profile
INSERT INTO mirt_profiles (user_id, child_profile, style_preferences, logistics, commerce)
VALUES (
    'test_memory_user_001',
    '{
        "name": "Марійка",
        "age": 7,
        "height_cm": 128,
        "gender": "дівчинка",
        "body_type": "стандартна"
    }'::jsonb,
    '{
        "favorite_models": ["Лагуна", "Ритм"],
        "favorite_colors": ["рожевий", "блакитний"],
        "avoided_colors": ["чорний"]
    }'::jsonb,
    '{
        "city": "Харків",
        "delivery_type": "nova_poshta",
        "favorite_branch": "Відділення №52"
    }'::jsonb,
    '{
        "avg_check": 1850,
        "total_orders": 3,
        "payment_preference": "card_online"
    }'::jsonb
)
ON CONFLICT (user_id) DO UPDATE SET 
    child_profile = EXCLUDED.child_profile,
    style_preferences = EXCLUDED.style_preferences,
    updated_at = NOW();

-- TEST 7.2: Select profile
SELECT 
    user_id,
    child_profile->>'name' as child_name,
    child_profile->>'height_cm' as height,
    style_preferences->'favorite_colors' as fav_colors,
    completeness_score
FROM mirt_profiles 
WHERE user_id = 'test_memory_user_001';

-- TEST 7.3: Verify completeness_score auto-calculation (trigger test)
-- Should be > 0 because we have child_profile, style_preferences, logistics, commerce
SELECT user_id, completeness_score 
FROM mirt_profiles 
WHERE user_id = 'test_memory_user_001';
-- Expected: completeness_score > 0.5

-- TEST 7.4: Update child height (simulate growth)
UPDATE mirt_profiles 
SET child_profile = jsonb_set(child_profile, '{height_cm}', '134')
WHERE user_id = 'test_memory_user_001';

-- TEST 7.5: Verify height update
SELECT child_profile->>'height_cm' as new_height 
FROM mirt_profiles 
WHERE user_id = 'test_memory_user_001';
-- Expected: 134

-- TEST 7.6: Add height history
UPDATE mirt_profiles 
SET child_profile = jsonb_set(
    child_profile, 
    '{height_history}', 
    '[{"date": "2024-06", "height": 128}, {"date": "2024-12", "height": 134}]'::jsonb
)
WHERE user_id = 'test_memory_user_001';

-- TEST 7.7: Query height history
SELECT 
    child_profile->'height_history' as height_history
FROM mirt_profiles 
WHERE user_id = 'test_memory_user_001';

-- TEST 7.8: Add favorite model to array
UPDATE mirt_profiles 
SET style_preferences = jsonb_set(
    style_preferences,
    '{favorite_models}',
    (style_preferences->'favorite_models') || '["Веселка"]'::jsonb
)
WHERE user_id = 'test_memory_user_001';

-- TEST 7.9: Verify favorite models
SELECT style_preferences->'favorite_models' as fav_models 
FROM mirt_profiles 
WHERE user_id = 'test_memory_user_001';
-- Expected: ["Лагуна", "Ритм", "Веселка"]

-- TEST 7.10: Update last_seen_at
UPDATE mirt_profiles SET last_seen_at = NOW() WHERE user_id = 'test_memory_user_001';

-- ============================================================================
-- TEST SUITE 8: MIRT_MEMORIES (Fluid Memory)
-- ============================================================================

-- TEST 8.1: Insert high-importance fact
INSERT INTO mirt_memories (user_id, content, fact_type, category, importance, surprise, confidence)
VALUES (
    'test_memory_user_001',
    'Дитина має алергію на синтетику',
    'constraint',
    'child',
    1.0,  -- Maximum importance
    0.9,  -- High surprise
    0.95  -- High confidence
);

-- TEST 8.2: Insert medium-importance fact
INSERT INTO mirt_memories (user_id, content, fact_type, category, importance, surprise, confidence)
VALUES (
    'test_memory_user_001',
    'Любить рожевий колір, особливо пудровий відтінок',
    'preference',
    'style',
    0.8,
    0.5,
    0.9
);

-- TEST 8.3: Insert low-importance fact (should be filtered by gating)
INSERT INTO mirt_memories (user_id, content, fact_type, category, importance, surprise, confidence)
VALUES (
    'test_memory_user_001',
    'Сказала привіт',
    'behavior',
    'child',
    0.2,  -- Low importance - should be ignored by gating
    0.1,  -- Low surprise
    1.0
);

-- TEST 8.4: Insert logistics fact
INSERT INTO mirt_memories (user_id, content, fact_type, category, importance, surprise, confidence)
VALUES (
    'test_memory_user_001',
    'Зручніше отримувати на поштомат, бо працює допізна',
    'preference',
    'delivery',
    0.7,
    0.6,
    0.85
);

-- TEST 8.5: Select all active memories for user
SELECT 
    id,
    content,
    fact_type,
    category,
    importance,
    surprise,
    is_active
FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' AND is_active = true
ORDER BY importance DESC;
-- Expected: 4 rows

-- TEST 8.6: Gating test - select only important facts (importance >= 0.6)
SELECT content, importance, surprise
FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' 
  AND is_active = true
  AND importance >= 0.6
ORDER BY importance DESC;
-- Expected: 3 rows (excludes "Сказала привіт")

-- TEST 8.7: Gating test - importance >= 0.6 AND surprise >= 0.4
SELECT content, importance, surprise
FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' 
  AND is_active = true
  AND importance >= 0.6
  AND surprise >= 0.4
ORDER BY importance DESC;
-- Expected: 3 rows (алергія, рожевий, поштомат)

-- TEST 8.8: Filter by category
SELECT content, category FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' AND category = 'style';
-- Expected: 1 row (рожевий колір)

-- TEST 8.9: Filter by fact_type
SELECT content, fact_type FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' AND fact_type = 'constraint';
-- Expected: 1 row (алергія)

-- TEST 8.10: Simulate time decay (decrease importance)
UPDATE mirt_memories 
SET importance = GREATEST(0.1, importance - 0.1)
WHERE user_id = 'test_memory_user_001' 
  AND content = 'Сказала привіт';

-- TEST 8.11: Verify decay
SELECT content, importance FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' AND content = 'Сказала привіт';
-- Expected: importance = 0.1

-- TEST 8.12: Deactivate old memory
UPDATE mirt_memories 
SET is_active = false
WHERE user_id = 'test_memory_user_001' AND content = 'Сказала привіт';

-- TEST 8.13: Count active vs inactive
SELECT is_active, COUNT(*) as count 
FROM mirt_memories 
WHERE user_id = 'test_memory_user_001'
GROUP BY is_active;
-- Expected: true=3, false=1

-- TEST 8.14: Update last_accessed_at
UPDATE mirt_memories 
SET last_accessed_at = NOW()
WHERE user_id = 'test_memory_user_001' AND is_active = true;

-- TEST 8.15: Version test - supersede old fact
-- First, get the ID of the pink color fact
WITH old_fact AS (
    SELECT id FROM mirt_memories 
    WHERE user_id = 'test_memory_user_001' 
    AND content LIKE '%рожевий%'
    LIMIT 1
)
INSERT INTO mirt_memories (user_id, content, fact_type, category, importance, surprise, superseded_by)
SELECT 
    'test_memory_user_001',
    'Тепер більше любить бузковий колір, ніж рожевий',
    'preference',
    'style',
    0.85,
    0.7,
    NULL
FROM old_fact;

-- ============================================================================
-- TEST SUITE 9: MIRT_MEMORY_SUMMARIES (Compressed Memory)
-- ============================================================================

-- TEST 9.1: Insert user summary
INSERT INTO mirt_memory_summaries (user_id, summary_type, summary_text, key_facts, facts_count, is_current)
VALUES (
    'test_memory_user_001',
    'user',
    'Постійна клієнтка з дочкою Марійкою (7 років, 134 см). Обережно ставиться до синтетики через алергію. Любить пастельні кольори. Зручно отримувати на поштомат.',
    ARRAY['алергія на синтетику', 'рожевий/бузковий', 'поштомат', 'зріст 134 см'],
    4,
    true
)
ON CONFLICT ON CONSTRAINT unique_current_user_summary DO UPDATE SET
    summary_text = EXCLUDED.summary_text,
    key_facts = EXCLUDED.key_facts,
    facts_count = EXCLUDED.facts_count,
    updated_at = NOW();

-- TEST 9.2: Select current summary
SELECT 
    summary_type,
    summary_text,
    key_facts,
    facts_count,
    is_current
FROM mirt_memory_summaries 
WHERE user_id = 'test_memory_user_001' AND is_current = true;

-- TEST 9.3: Check key_facts array
SELECT unnest(key_facts) as key_fact
FROM mirt_memory_summaries 
WHERE user_id = 'test_memory_user_001' AND is_current = true;
-- Expected: 4 rows

-- TEST 9.4: Update summary
UPDATE mirt_memory_summaries 
SET 
    summary_text = summary_text || ' Середній чек ~1850 грн.',
    updated_at = NOW()
WHERE user_id = 'test_memory_user_001' AND is_current = true;

-- ============================================================================
-- TEST SUITE 10: MEMORY FUNCTIONS
-- ============================================================================

-- TEST 10.1: Test calculate_profile_completeness function
SELECT calculate_profile_completeness(p.*) as completeness
FROM mirt_profiles p
WHERE user_id = 'test_memory_user_001';
-- Expected: value between 0.5 and 1.0

-- TEST 10.2: Test apply_memory_decay function
SELECT apply_memory_decay();
-- Expected: returns number of affected rows

-- TEST 10.3: Verify decay was applied (check updated_at changed)
SELECT content, importance, updated_at 
FROM mirt_memories 
WHERE user_id = 'test_memory_user_001' 
ORDER BY updated_at DESC;

-- ============================================================================
-- TEST SUITE 11: MEMORY JOINS & COMPLEX QUERIES
-- ============================================================================

-- TEST 11.1: Profile with memory count
SELECT 
    p.user_id,
    p.child_profile->>'name' as child_name,
    COUNT(m.id) as total_memories,
    SUM(CASE WHEN m.is_active THEN 1 ELSE 0 END) as active_memories
FROM mirt_profiles p
LEFT JOIN mirt_memories m ON p.user_id = m.user_id
WHERE p.user_id = 'test_memory_user_001'
GROUP BY p.user_id, p.child_profile;

-- TEST 11.2: Profile with summary
SELECT 
    p.user_id,
    p.completeness_score,
    s.summary_text,
    s.facts_count
FROM mirt_profiles p
LEFT JOIN mirt_memory_summaries s ON p.user_id = s.user_id AND s.is_current = true
WHERE p.user_id = 'test_memory_user_001';

-- TEST 11.3: Full memory context query (what memory_context_node uses)
SELECT 
    p.child_profile,
    p.style_preferences,
    p.logistics,
    p.commerce,
    s.summary_text as recent_summary,
    (
        SELECT json_agg(json_build_object(
            'content', m.content,
            'importance', m.importance,
            'category', m.category
        ) ORDER BY m.importance DESC)
        FROM mirt_memories m
        WHERE m.user_id = p.user_id AND m.is_active = true AND m.importance >= 0.6
        LIMIT 10
    ) as top_facts
FROM mirt_profiles p
LEFT JOIN mirt_memory_summaries s ON p.user_id = s.user_id AND s.is_current = true
WHERE p.user_id = 'test_memory_user_001';

-- ============================================================================
-- CLEANUP: Remove test memory data
-- ============================================================================

-- DELETE FROM mirt_memory_summaries WHERE user_id = 'test_memory_user_001';
-- DELETE FROM mirt_memories WHERE user_id = 'test_memory_user_001';
-- DELETE FROM mirt_profiles WHERE user_id = 'test_memory_user_001';

-- ============================================================================
-- SUMMARY: Expected Results
-- ============================================================================
-- TEST 7.x: mirt_profiles JSONB + trigger works ✓
-- TEST 8.x: mirt_memories with gating logic works ✓
-- TEST 9.x: mirt_memory_summaries works ✓
-- TEST 10.x: Memory functions work ✓
-- TEST 11.x: Complex JOINs work ✓
