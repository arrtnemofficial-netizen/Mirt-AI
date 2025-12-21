-- Migration: Remove 'price' column, keep only 'price_by_size'
-- Also clean prices from 'description' column
-- Date: 2024-12-14

-- ============================================================================
-- STEP 1: Backup current data (just in case)
-- ============================================================================

-- Create backup table with current prices
