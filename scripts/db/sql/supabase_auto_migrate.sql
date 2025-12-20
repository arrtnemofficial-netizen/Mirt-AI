-- ============================================================================
-- АВТОМАТИЧНА МІГРАЦІЯ PRODUCTS ДЛЯ VISION AI
-- ============================================================================
-- Цей скрипт:
-- 1. Додає нові колонки (якщо не існують)
-- 2. Автоматично заповнює їх на основі назви товару
-- 
-- ВИКОНАЙ В SUPABASE SQL EDITOR ОДНИМ КЛІКОМ!
-- ============================================================================


-- ============================================================================
-- КРОК 1: ДОДАТИ КОЛОНКИ
-- ============================================================================

ALTER TABLE public.products ADD COLUMN IF NOT EXISTS sku TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS color TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS fabric_type TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS closure_type TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS has_hood BOOLEAN DEFAULT false;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS pants_style TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS special_features TEXT[];
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS visual_markers JSONB;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS back_view_description TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS recognition_tips TEXT[];
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS confused_with TEXT[];
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS photo_url TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS in_stock BOOLEAN DEFAULT true;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS stock_quantity INTEGER DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;


-- ============================================================================
-- КРОК 2: ВСТАНОВИТИ ДЕФОЛТИ
-- ============================================================================

UPDATE public.products SET in_stock = true WHERE in_stock IS NULL;
UPDATE public.products SET is_active = true WHERE is_active IS NULL;


-- ============================================================================
-- КРОК 3: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ МРІЯ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'плюш',
    closure_type = 'half_zip',
    has_hood = false,
    pants_style = 'joggers',
    back_view_description = 'гладка спина без прикрас, тільки шви',
    recognition_tips = ARRAY[
        'ГОЛОВНА ОЗНАКА: half-zip (коротка блискавка до грудей)',
        'Плюшева м''яка тканина з ворсом',
        'Джогери з манжетами знизу'
    ],
    confused_with = ARRAY['Костюм Лагуна']
WHERE name ILIKE '%Мрія%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 4: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ ЛАГУНА
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'плюш',
    closure_type = 'full_zip',
    has_hood = false,
    pants_style = 'joggers',
    back_view_description = 'гладка спина, шви по боках',
    recognition_tips = ARRAY[
        'ПОВНА БЛИСКАВКА на всю довжину!',
        'Стоячий комір',
        'Плюшева тканина як у Мрії'
    ],
    confused_with = ARRAY['Костюм Мрія']
WHERE name ILIKE '%Лагуна%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 5: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ РИТМ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'бавовна',
    closure_type = 'no_zip',
    has_hood = true,
    pants_style = 'joggers',
    back_view_description = 'об''ємна спина, капюшон видно',
    recognition_tips = ARRAY[
        'КАПЮШОН - головна відмінність!',
        'Oversize крій',
        'Гладка бавовна, не плюш'
    ],
    confused_with = ARRAY['Костюм Каприз']
WHERE name ILIKE '%Ритм%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 6: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ КАПРИЗ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'бавовна',
    closure_type = 'no_zip',
    has_hood = false,
    pants_style = 'palazzo',
    back_view_description = 'гладка спина світшота',
    recognition_tips = ARRAY[
        'ШИРОКІ ШТАНИ palazzo - головна ознака!',
        'БЕЗ капюшона',
        'БЕЗ блискавки'
    ],
    confused_with = ARRAY['Костюм Ритм', 'Костюм Валері']
WHERE name ILIKE '%Каприз%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 7: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ ВАЛЕРІ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'бавовна',
    closure_type = 'no_zip',
    has_hood = false,
    pants_style = 'palazzo',
    back_view_description = 'смужки видно і зі спини',
    recognition_tips = ARRAY[
        'СМУЖКИ на блузі - головна ознака!',
        'Широкі штани palazzo'
    ],
    confused_with = ARRAY['Костюм Каприз']
WHERE name ILIKE '%Валері%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 8: АВТОЗАПОВНЕННЯ ДЛЯ КОСТЮМ МЕРЕЯ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'трикотаж',
    closure_type = 'no_zip',
    has_hood = true,
    pants_style = 'joggers',
    back_view_description = 'лампаси видно ззаду по боках штанів',
    recognition_tips = ARRAY[
        'ЛАМПАСИ по боках штанів - 100% Мерея!',
        'Капюшон є',
        'Спортивний стиль'
    ],
    confused_with = ARRAY[]::TEXT[]
WHERE name ILIKE '%Мерея%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 9: АВТОЗАПОВНЕННЯ ДЛЯ ТРЕНЧ
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'екошкіра',
    closure_type = 'buttons',
    has_hood = false,
    pants_style = NULL,
    back_view_description = 'шлиця ззаду, пояс',
    recognition_tips = ARRAY[
        'БЛИСК екошкіри - видно на будь-якому фото!',
        'Пояс на талії',
        'Довжина міді'
    ],
    confused_with = ARRAY[]::TEXT[]
WHERE name ILIKE '%Тренч%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 10: АВТОЗАПОВНЕННЯ ДЛЯ СУКНЯ АННА
-- ============================================================================

UPDATE public.products
SET 
    fabric_type = 'поплін',
    closure_type = 'buttons',
    has_hood = false,
    pants_style = NULL,
    back_view_description = 'застібка на блискавці по спині',
    recognition_tips = ARRAY[
        'А-силует (розширюється донизу)',
        'Манжети на гудзиках',
        'Щільна тканина тримає форму'
    ],
    confused_with = ARRAY[]::TEXT[]
WHERE name ILIKE '%Анна%' AND fabric_type IS NULL;


-- ============================================================================
-- КРОК 11: АВТОЗАПОВНЕННЯ КОЛЬОРІВ
-- ============================================================================

-- Рожевий / Пудра
UPDATE public.products SET color = 'рожевий' WHERE name ILIKE '%рожев%' AND color IS NULL;
UPDATE public.products SET color = 'пудра' WHERE name ILIKE '%пудр%' AND color IS NULL;

-- Молочний / Білий
UPDATE public.products SET color = 'молочний' WHERE name ILIKE '%молоч%' AND color IS NULL;
UPDATE public.products SET color = 'білий' WHERE name ILIKE '%біл%' AND color IS NULL;

-- Темні
UPDATE public.products SET color = 'чорний' WHERE name ILIKE '%чорн%' AND color IS NULL;
UPDATE public.products SET color = 'графіт' WHERE name ILIKE '%графіт%' AND color IS NULL;
UPDATE public.products SET color = 'сірий' WHERE name ILIKE '%сір%' AND color IS NULL;

-- Бежеві
UPDATE public.products SET color = 'бежевий' WHERE name ILIKE '%бежев%' AND color IS NULL;
UPDATE public.products SET color = 'капучіно' WHERE name ILIKE '%капучіно%' AND color IS NULL;
UPDATE public.products SET color = 'шоколадний' WHERE name ILIKE '%шоколад%' AND color IS NULL;

-- Інші
UPDATE public.products SET color = 'хакі' WHERE name ILIKE '%хакі%' AND color IS NULL;
UPDATE public.products SET color = 'бордо' WHERE name ILIKE '%бордо%' AND color IS NULL;
UPDATE public.products SET color = 'синій' WHERE name ILIKE '%синій%' OR name ILIKE '%синя%' AND color IS NULL;
UPDATE public.products SET color = 'жовтий' WHERE name ILIKE '%жовт%' AND color IS NULL;
UPDATE public.products SET color = 'зелений' WHERE name ILIKE '%зелен%' AND color IS NULL;
UPDATE public.products SET color = 'фіолетовий' WHERE name ILIKE '%фіолет%' AND color IS NULL;
UPDATE public.products SET color = 'малиновий' WHERE name ILIKE '%малинов%' AND color IS NULL;
UPDATE public.products SET color = 'помаранчевий' WHERE name ILIKE '%помаранч%' AND color IS NULL;


-- ============================================================================
-- КРОК 12: ПЕРЕВІРКА РЕЗУЛЬТАТУ
-- ============================================================================

SELECT 
    name,
    color,
    fabric_type,
    closure_type,
    has_hood,
    pants_style,
    recognition_tips[1] as main_tip
FROM public.products
ORDER BY name
LIMIT 20;


-- ============================================================================
-- СТАТИСТИКА
-- ============================================================================

SELECT 
    'Total products' as metric, 
    COUNT(*)::text as value 
FROM public.products

UNION ALL

SELECT 
    'With fabric_type', 
    COUNT(*)::text 
FROM public.products 
WHERE fabric_type IS NOT NULL

UNION ALL

SELECT 
    'With color', 
    COUNT(*)::text 
FROM public.products 
WHERE color IS NOT NULL

UNION ALL

SELECT 
    'Active', 
    COUNT(*)::text 
FROM public.products 
WHERE is_active = true;
