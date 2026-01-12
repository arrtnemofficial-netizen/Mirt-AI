-- ============================================================================
-- USERS TABLE
-- ============================================================================
-- Registry of all known users across platforms (Telegram/Instagram/ManyChat).
-- Used by src/services/storage/postgres_message_store.py

create table if not exists users (
    user_id text primary key, -- Unified ID (or platform specific if not merged)
    username text, -- Display name or nickname
    
    -- Platform handles
    telegram_username text,
    instagram_username text,
    
    -- Activity tracking
    last_interaction_at timestamptz default now(),
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- Indexes
create index if not exists idx_users_telegram_username on users(telegram_username);
create index if not exists idx_users_instagram_username on users(instagram_username);
create index if not exists idx_users_last_interaction on users(last_interaction_at desc);
