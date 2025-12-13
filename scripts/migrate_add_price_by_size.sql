-- ============================================================================
-- MIGRATION: Add price_by_size JSONB column to products table
-- ============================================================================
-- 
-- Це дозволяє зберігати варіативні ціни для товарів типу Лагуна/Мрія:
-- {
--   "80-92": 1590,
--   "98-104": 1790,
--   "110-116": 1990,
--   "122-128": 2190,
--   "134-140": 2290,
--   "146-152": 2390,
--   "158-164": 2390
-- }
--
-- Якщо price_by_size IS NULL — використовуй price (єдина ціна для всіх розмірів)
-- Якщо price_by_size IS NOT NULL — ціна залежить від розміру
-- ============================================================================

-- 1. Додаємо колонку price_by_size
ALTER TABLE products 
ADD COLUMN IF NOT EXISTS price_by_size JSONB DEFAULT NULL;

-- 2. Додаємо колонку closure_type для розрізнення Лагуна vs Мрія
ALTER TABLE products 
ADD COLUMN IF NOT EXISTS closure_type VARCHAR(20) DEFAULT NULL;
-- Можливі значення: 'full_zip', 'half_zip', 'no_zip', 'buttons'

-- 3. Додаємо колонку material для текстури
ALTER TABLE products 
ADD COLUMN IF NOT EXISTS material VARCHAR(100) DEFAULT NULL;
-- Наприклад: 'плюш', 'бавовна', 'екошкіра'

-- 4. Коментар для документації
COMMENT ON COLUMN products.price_by_size IS 'JSONB map of size->price. NULL = use single price field for all sizes.';
COMMENT ON COLUMN products.closure_type IS 'Closure type for vision identification: full_zip, half_zip, no_zip, buttons';
COMMENT ON COLUMN products.material IS 'Material type for vision identification: плюш, бавовна, екошкіра';

-- ============================================================================
-- Оновлення даних для Лагуна (full_zip) та Мрія (half_zip)
-- ============================================================================

-- Костюм Лагуна — ПОВНА блискавка
UPDATE products SET 
  closure_type = 'full_zip',
  material = 'плюш',
  price_by_size = '{"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390}'::jsonb
WHERE name LIKE 'Костюм Лагуна%';

-- Костюм Мрія — HALF-ZIP
UPDATE products SET 
  closure_type = 'half_zip',
  material = 'плюш',
  price_by_size = '{"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390}'::jsonb
WHERE name LIKE 'Костюм Мрія%';

-- Костюм Мерея — без блискавки
UPDATE products SET 
  closure_type = 'no_zip',
  material = 'трикотаж',
  price_by_size = '{"80-92": 1985, "98-104": 1985, "110-116": 1985, "122-128": 1985, "134-140": 2150, "146-152": 2150, "158-164": 2150}'::jsonb
WHERE name LIKE 'Костюм Мерея%';

-- Костюм Ритм — без блискавки, з капюшоном
UPDATE products SET 
  closure_type = 'no_zip',
  material = 'бавовна'
WHERE name LIKE 'Костюм Ритм%';

-- Костюм Каприз — без блискавки
UPDATE products SET 
  closure_type = 'no_zip',
  material = 'бавовна'
WHERE name LIKE 'Костюм Каприз%';

-- Тренч екошкіра — гудзики
UPDATE products SET 
  closure_type = 'buttons',
  material = 'екошкіра'
WHERE name LIKE 'Тренч екошкіра%';

-- Тренч тканинний — гудзики
UPDATE products SET 
  closure_type = 'buttons',
  material = 'костюмна тканина'
WHERE name LIKE 'Тренч (%';

-- ============================================================================
-- Перевірка
-- ============================================================================
-- SELECT name, price, price_by_size, closure_type, material FROM products;
