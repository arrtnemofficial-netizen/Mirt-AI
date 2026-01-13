-- =============================================================================
-- ТЕСТ: Перевірка price_by_size після міграції
-- =============================================================================
-- Запустити ПІСЛЯ виконання 003_add_price_by_size.sql
-- Очікуваний результат: 9 товарів з price_by_size NOT NULL
-- =============================================================================

-- 1. Перевірити що колонка існує і заповнена
SELECT 
  name, 
  price,
  price_by_size,
  price_by_size->>'122-128' AS price_for_128
FROM products 
WHERE price_by_size IS NOT NULL
ORDER BY name;

-- 2. Перевірити Костюм Лагуна (рожевий) - ціна для 122-128 має бути 2190
SELECT 
  name,
  (price_by_size->>'122-128')::numeric AS expected_2190,
  (price_by_size->>'80-92')::numeric AS expected_1590
FROM products 
WHERE name = 'Костюм Лагуна (рожевий)';

-- 3. Перевірити Костюм Мерея - ціна для 134-140 має бути 2150
SELECT 
  name,
  (price_by_size->>'134-140')::numeric AS expected_2150,
  (price_by_size->>'122-128')::numeric AS expected_1985
FROM products 
WHERE name LIKE 'Костюм Мерея%';

-- 4. Порахувати скільки товарів оновлено
SELECT COUNT(*) AS updated_count FROM products WHERE price_by_size IS NOT NULL;
-- Очікується: 9

-- 5. Переконатись що інші товари НЕ зачеплені (price_by_size = NULL)
SELECT name, price FROM products WHERE price_by_size IS NULL LIMIT 5;
