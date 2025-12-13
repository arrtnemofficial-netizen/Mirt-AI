-- ============================================================================
-- MIRT MEMORY SYSTEM - AGI-Style Memory Layer (Titans-like)
-- ============================================================================
-- 3-рівнева архітектура памʼяті:
--   1. mirt_profiles    → Persistent Memory (ніколи не забувається)
--   2. mirt_memories    → Fluid Memory (атомарні факти з importance/surprise)
--   3. mirt_memory_summaries → Compressed Memory (стислі summary)
-- ============================================================================

-- Enable pgvector extension for semantic search
create extension if not exists vector;

-- ============================================================================
-- 1. PERSISTENT MEMORY - User Profiles
-- ============================================================================
-- Те, що майже ніколи не забувається і завжди завантажується перед сесією.
-- Аналог Persistent Memory в Titans: стабільні факти про користувача.

create table if not exists mirt_profiles (
    id bigint primary key generated always as identity,
    user_id text unique not null, -- External ID (Telegram/ManyChat/Instagram)
    
    -- Child Profile (дитячий одяг - доменна специфіка)
    child_profile jsonb default '{}'::jsonb,
    -- Структура: {
    --   "name": "Марійка",
    --   "age": 7,
    --   "height_cm": 128,
    --   "height_history": [{"date": "2024-01", "height": 122}, {"date": "2024-06", "height": 128}],
    --   "body_type": "стандартна", -- стандартна, худорлява, повненька
    --   "gender": "дівчинка"
    -- }
    
    -- Style Preferences
    style_preferences jsonb default '{}'::jsonb,
    -- Структура: {
    --   "favorite_models": ["Лагуна", "Ритм", "Веселка"],
    --   "preferred_styles": ["спортивний", "святковий"],
    --   "favorite_colors": ["рожевий", "блакитний"],
    --   "avoided_colors": ["чорний"],
    --   "fabric_preferences": ["бавовна", "не синтетика"]
    -- }
    
    -- Logistics
    logistics jsonb default '{}'::jsonb,
    -- Структура: {
    --   "city": "Харків",
    --   "delivery_type": "nova_poshta",
    --   "favorite_branch": "Відділення №52",
    --   "address": "вул. Сумська 25"
    -- }
    
    -- Commerce Behavior
    commerce jsonb default '{}'::jsonb,
    -- Структура: {
    --   "avg_check": 1850,
    --   "order_frequency": "monthly",
    --   "discount_sensitive": true,
    --   "payment_preference": "card_online",
    --   "total_orders": 5,
    --   "last_order_date": "2024-12-01"
    -- }
    
    -- Metadata
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    last_seen_at timestamptz default now(),
    
    -- Profile completeness score (0.0-1.0) - auto-calculated
    completeness_score float default 0.0
);

create index if not exists idx_mirt_profiles_user_id on mirt_profiles(user_id);
create index if not exists idx_mirt_profiles_last_seen on mirt_profiles(last_seen_at desc);

-- ============================================================================
-- 2. FLUID MEMORY - Atomic Facts
-- ============================================================================
-- Атомарні факти про конкретного користувача, діалог або покупку.
-- Аналог Fluid Memory з Titans: окремі фрагменти, які можна вибирати
-- через векторний пошук або по категоріях.
--
-- КЛЮЧОВІ ПОЛЯ для Titans-like gating:
--   - importance (0.0-1.0): наскільки факт впливає на рекомендації
--   - surprise (0.0-1.0): наскільки це нова/неочікувана інформація
--
-- Gating rule: записуємо тільки якщо importance >= 0.6 AND surprise >= 0.4

create table if not exists mirt_memories (
    id uuid primary key default gen_random_uuid(),
    user_id text not null references mirt_profiles(user_id) on delete cascade,
    session_id text, -- Опціонально: привʼязка до конкретної сесії
    
    -- Fact Content
    content text not null, -- Сам факт у вільній формі
    
    -- Fact Classification
    fact_type text not null, -- preference, constraint, logistics, behavior, feedback
    category text not null, -- child, style, delivery, payment, product, complaint
    
    -- Titans-like Metrics (КРИТИЧНІ для gating!)
    importance float not null default 0.5, -- 0.0-1.0: вплив на рекомендації
    surprise float not null default 0.5,   -- 0.0-1.0: новизна інформації
    confidence float not null default 0.8, -- 0.0-1.0: впевненість у факті
    
    -- Time-based decay
    ttl_days int, -- Через скільки днів можна видалити/знизити вагу (null = вічний)
    decay_rate float default 0.01, -- На скільки знижувати importance за день
    
    -- Vector embedding for semantic search
    embedding vector(1536), -- Compatible with text-embedding-3-small
    
    -- Lifecycle
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    last_accessed_at timestamptz default now(),
    expires_at timestamptz, -- Якщо ttl_days заданий: created_at + ttl_days
    
    -- Versioning (для оновлення фактів)
    version int default 1,
    superseded_by uuid references mirt_memories(id), -- Якщо факт замінено новим
    is_active boolean default true
);

-- Indexes for efficient querying
create index if not exists idx_mirt_memories_user_id on mirt_memories(user_id);
create index if not exists idx_mirt_memories_user_active on mirt_memories(user_id, is_active) where is_active = true;
create index if not exists idx_mirt_memories_type on mirt_memories(fact_type);
create index if not exists idx_mirt_memories_category on mirt_memories(category);
create index if not exists idx_mirt_memories_importance on mirt_memories(importance desc) where is_active = true;
create index if not exists idx_mirt_memories_expires on mirt_memories(expires_at) where expires_at is not null;

-- Vector similarity search index (HNSW for speed)
create index if not exists idx_mirt_memories_embedding on mirt_memories 
using hnsw (embedding vector_cosine_ops)
where embedding is not null and is_active = true;

-- ============================================================================
-- 3. COMPRESSED MEMORY - Summaries
-- ============================================================================
-- Короткі summary для зменшення токенів в промпті.
-- Замість 100 фактів даємо 2-3 стислі блоки.

create table if not exists mirt_memory_summaries (
    id bigint primary key generated always as identity,
    
    -- Reference (один з трьох типів)
    user_id text references mirt_profiles(user_id) on delete cascade,
    product_id bigint, -- Для product-level summaries
    session_id text,   -- Для session-level summaries
    
    -- Summary Type
    summary_type text not null, -- user, product, session
    
    -- Content
    summary_text text not null, -- Стислий текст summary
    key_facts text[], -- Масив ключових фактів (для quick access)
    
    -- Metadata
    facts_count int default 0, -- Скільки фактів узагальнено
    time_range_start timestamptz, -- Початок періоду
    time_range_end timestamptz,   -- Кінець періоду
    
    -- Lifecycle
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    is_current boolean default true, -- Чи це актуальний summary
    
    -- Constraint: тільки один current summary per user/product/session
    constraint unique_current_user_summary unique (user_id, summary_type, is_current) 
        deferrable initially deferred
);

create index if not exists idx_mirt_summaries_user on mirt_memory_summaries(user_id) where is_current = true;
create index if not exists idx_mirt_summaries_type on mirt_memory_summaries(summary_type);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function to calculate profile completeness
create or replace function calculate_profile_completeness(profile_row mirt_profiles)
returns float as $$
declare
    score float := 0.0;
    max_score float := 0.0;
begin
    -- Child profile (30% weight)
    max_score := max_score + 0.3;
    if profile_row.child_profile ? 'height_cm' then score := score + 0.15; end if;
    if profile_row.child_profile ? 'age' then score := score + 0.1; end if;
    if profile_row.child_profile ? 'gender' then score := score + 0.05; end if;
    
    -- Style preferences (25% weight)
    max_score := max_score + 0.25;
    if profile_row.style_preferences ? 'favorite_models' then score := score + 0.1; end if;
    if profile_row.style_preferences ? 'favorite_colors' then score := score + 0.1; end if;
    if profile_row.style_preferences ? 'preferred_styles' then score := score + 0.05; end if;
    
    -- Logistics (25% weight)
    max_score := max_score + 0.25;
    if profile_row.logistics ? 'city' then score := score + 0.15; end if;
    if profile_row.logistics ? 'favorite_branch' then score := score + 0.1; end if;
    
    -- Commerce (20% weight)
    max_score := max_score + 0.2;
    if profile_row.commerce ? 'total_orders' and (profile_row.commerce->>'total_orders')::int > 0 then 
        score := score + 0.1; 
    end if;
    if profile_row.commerce ? 'payment_preference' then score := score + 0.1; end if;
    
    return round((score / max_score)::numeric, 2);
end;
$$ language plpgsql immutable;

-- Trigger to auto-update completeness score
create or replace function update_profile_completeness()
returns trigger as $$
begin
    new.completeness_score := calculate_profile_completeness(new);
    new.updated_at := now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_profile_completeness on mirt_profiles;
create trigger trg_profile_completeness
    before insert or update on mirt_profiles
    for each row execute function update_profile_completeness();

-- Function to apply time decay to memories
create or replace function apply_memory_decay()
returns int as $$
declare
    affected_rows int;
begin
    -- Зменшуємо importance для старих фактів
    update mirt_memories
    set 
        importance = greatest(0.1, importance - decay_rate),
        updated_at = now()
    where 
        is_active = true
        and decay_rate > 0
        and last_accessed_at < now() - interval '1 day';
    
    get diagnostics affected_rows = row_count;
    
    -- Деактивуємо expired факти
    update mirt_memories
    set 
        is_active = false,
        updated_at = now()
    where 
        is_active = true
        and expires_at is not null
        and expires_at < now();
    
    return affected_rows;
end;
$$ language plpgsql;

-- Function for semantic memory search
create or replace function search_memories(
    p_user_id text,
    p_query_embedding vector(1536),
    p_limit int default 10,
    p_min_importance float default 0.3,
    p_categories text[] default null
)
returns table (
    id uuid,
    content text,
    fact_type text,
    category text,
    importance float,
    surprise float,
    similarity float
) as $$
begin
    return query
    select 
        m.id,
        m.content,
        m.fact_type,
        m.category,
        m.importance,
        m.surprise,
        1 - (m.embedding <=> p_query_embedding) as similarity
    from mirt_memories m
    where 
        m.user_id = p_user_id
        and m.is_active = true
        and m.importance >= p_min_importance
        and (p_categories is null or m.category = any(p_categories))
        and m.embedding is not null
    order by 
        (1 - (m.embedding <=> p_query_embedding)) * m.importance desc
    limit p_limit;
end;
$$ language plpgsql stable;

-- ============================================================================
-- RLS POLICIES
-- ============================================================================
alter table mirt_profiles enable row level security;
alter table mirt_memories enable row level security;
alter table mirt_memory_summaries enable row level security;

-- Service role bypasses RLS, these are for reference
create policy "Users can view own profile"
on mirt_profiles for select
using (true); -- Service role access

create policy "Users can view own memories"
on mirt_memories for select
using (true); -- Service role access

create policy "Users can view own summaries"
on mirt_memory_summaries for select
using (true); -- Service role access

-- ============================================================================
-- COMMENTS
-- ============================================================================
comment on table mirt_profiles is 'Persistent Memory: stable user profiles that rarely change (Titans-like)';
comment on table mirt_memories is 'Fluid Memory: atomic facts with importance/surprise gating (Titans-like)';
comment on table mirt_memory_summaries is 'Compressed Memory: summarized facts to reduce prompt tokens';

comment on column mirt_memories.importance is 'Impact score (0-1): how much this fact affects recommendations';
comment on column mirt_memories.surprise is 'Novelty score (0-1): how unexpected/new this information is';
comment on column mirt_memories.decay_rate is 'Daily decay for importance (Titans-like temporal forgetting)';
