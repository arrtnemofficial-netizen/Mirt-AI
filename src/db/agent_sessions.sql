-- ============================================================================
-- AGENT SESSIONS TABLE
-- ============================================================================
-- Stores the serialized LangGraph state for each session.
-- Used by src/services/storage/postgres_store.py

create table if not exists agent_sessions (
    session_id text primary key,
    state jsonb not null, -- Serialized ConversationState
    updated_at timestamptz default now()
);

-- Index for fast lookups (redundant with PK but listed for completeness if needed)
-- create index if not exists idx_agent_sessions_id on agent_sessions(session_id);
