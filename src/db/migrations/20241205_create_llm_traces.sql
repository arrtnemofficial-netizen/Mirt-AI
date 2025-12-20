-- Create ENUMs for status and error categorization
DO $$ BEGIN
    CREATE TYPE trace_status AS ENUM ('SUCCESS', 'ERROR', 'BLOCKED', 'ESCALATED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE error_category AS ENUM ('SCHEMA', 'BUSINESS', 'SAFETY', 'SYSTEM');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create the main traces table
CREATE TABLE IF NOT EXISTS public.llm_traces (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    session_id text NOT NULL,
    trace_id uuid NOT NULL, -- Links logical steps within a single request processing
    
    -- Execution Context
    node_name text NOT NULL,      -- e.g., 'agent_node', 'vision_node', 'validation_node'
    state_name text,              -- e.g., 'STATE_4_OFFER'
    prompt_key text,              -- e.g., 'system.main', 'state.STATE_4_OFFER'
    prompt_version text,          -- e.g., '1.2.0'
    prompt_label text,            -- e.g., 'prod', 'exp'
    
    -- Data Payload (Snapshots)
    input_snapshot jsonb,         -- The input responsible for this step (user message or internal state)
    output_snapshot jsonb,        -- The raw result (agent response, tool output, or validation breakdown)
    
    -- Outcome & Reliability
    status trace_status NOT NULL DEFAULT 'SUCCESS',
    error_category error_category, -- Only if status != SUCCESS
    error_message text,            -- Human-readable error details
    
    -- Performance Metrics
    latency_ms float,             -- Execution time in milliseconds
    tokens_in int,               -- Input tokens used
    tokens_out int,              -- Output tokens generated
    cost float,                  -- Estimated cost
    
    -- Metadata
    model_name text               -- e.g., 'gpt-4o', 'grok-beta'
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_llm_traces_session ON llm_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_traces_created ON llm_traces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_traces_trace_id ON llm_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_llm_traces_status ON llm_traces(status) WHERE status != 'SUCCESS';
