-- RESTORE description from backup after broken migration
-- Date: 2024-12-14

-- ============================================================================
-- RESTORE description from backup table
-- ============================================================================

UPDATE products p
SET description = b.description
FROM products_price_backup b
WHERE p.id = b.id
  AND b.description IS NOT NULL;

-- Verify restoration
SELECT id, name, LEFT(description, 80) as description_preview
FROM products
WHERE description IS NOT NULL
LIMIT 5;
