-- ============================================================================
-- MESSAGES TABLE
-- ============================================================================
-- Stores raw chat history for analysis and context.
-- Used by src/services/storage/postgres_message_store.py

create table if not exists messages (
    id bigint primary key generated always as identity,
    session_id text not null,
    role text not null, -- 'user', 'assistant'
    content text not null,
    content_type text default 'text', -- 'text', 'image'
    user_id text, -- NULLABLE, links to external user ID
    tags text[] default '{}',
    created_at timestamptz default now()
);

create index if not exists idx_messages_session_id on messages(session_id);
create index if not exists idx_messages_user_id on messages(user_id);
create index if not exists idx_messages_created_at on messages(created_at);
