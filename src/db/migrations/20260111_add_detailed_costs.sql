-- ============================================================================
-- MIGRATION: 20260111_add_detailed_costs.sql
-- ============================================================================
-- Adds detailed cost tracking columns for USD and UAH to both llm_traces and llm_usage.

-- 1. Update llm_traces
ALTER TABLE llm_traces
ADD COLUMN IF NOT EXISTS cost_usd numeric(10, 6),
ADD COLUMN IF NOT EXISTS cost_uah numeric(10, 6);

COMMENT ON COLUMN llm_traces.cost_usd IS 'Cost in USD at time of transaction';
COMMENT ON COLUMN llm_traces.cost_uah IS 'Cost in UAH at time of transaction (Rate: 43.17)';

-- Backfill existing cost to cost_usd if needed
UPDATE llm_traces
SET cost_usd = cost
WHERE cost_usd IS NULL AND cost IS NOT NULL;

-- 2. Update llm_usage (Primary Billing Table)
ALTER TABLE llm_usage
ADD COLUMN IF NOT EXISTS cost_uah numeric(10, 6);

COMMENT ON COLUMN llm_usage.cost_uah IS 'Cost in UAH at time of transaction';

-- Backfill llm_usage cost_uah based on rate 43.17 (approximate for past data)
UPDATE llm_usage
SET cost_uah = cost_usd * 43.17
WHERE cost_uah IS NULL AND cost_usd IS NOT NULL;
