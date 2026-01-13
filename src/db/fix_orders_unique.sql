-- Fix race condition in orders table by adding UNIQUE constraint on session_id
-- Run this migration in Supabase to prevent duplicate orders

-- First, clean up any existing duplicates (keep the latest one)
WITH ranked_orders AS (
    SELECT 
        id,
        session_id,
        ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at DESC) as rn
    FROM public.orders
    WHERE session_id IS NOT NULL
),
duplicates_to_delete AS (
    SELECT id
    FROM ranked_orders
    WHERE rn > 1
)
DELETE FROM public.orders
WHERE id IN (SELECT id FROM duplicates_to_delete);

-- Add UNIQUE constraint on session_id
ALTER TABLE public.orders 
ADD CONSTRAINT orders_session_id_unique UNIQUE (session_id);

-- Optional: Add index for faster lookups (if not exists)
CREATE INDEX IF NOT EXISTS idx_orders_session_id_unique ON public.orders (session_id);

-- Grant permissions
GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT ALL ON public.orders TO anon, authenticated;
