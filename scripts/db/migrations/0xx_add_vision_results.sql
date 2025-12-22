-- Vision Results Ledger (idempotency for Vision layer)
create extension if not exists pgcrypto; -- for gen_random_uuid (if not enabled)

create table if not exists vision_results (
    vision_result_id uuid primary key default gen_random_uuid(),
    session_id text not null,
    image_hash text not null,
    status text not null default 'processed', -- processed | escalated | blocked | failed
    confidence numeric,
    identified_product jsonb,
    metadata jsonb,
    error_message text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create unique index if not exists ux_vision_results_image_hash on vision_results(image_hash);
create index if not exists idx_vision_results_status on vision_results(status);
