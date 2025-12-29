-- ============================================================================
-- MIGRATION: Add Vision Rules Columns
-- ============================================================================
-- Purpose: Enable "Smart DB" architecture where logic lives in the database.
-- Adds JSONB columns to store visual markers and distinction rules.

ALTER TABLE products 
ADD COLUMN IF NOT EXISTS visual_rules JSONB DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS distinction_rules JSONB DEFAULT '{}'::jsonb;

-- Comment on columns for clarity
COMMENT ON COLUMN products.visual_rules IS 'Visual recognition markers (fabric, key_features) from products_master.yaml';
COMMENT ON COLUMN products.distinction_rules IS 'Logic for distinguishing similar products (confused_with, critical_check)';
