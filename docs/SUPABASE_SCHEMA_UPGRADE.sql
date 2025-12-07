-- ============================================================================
-- SUPABASE SCHEMA UPGRADE FOR VISION AI
-- ============================================================================
-- Виконай цей SQL в Supabase SQL Editor
-- ============================================================================

-- 1. ДОДАЄМО КОЛОНКИ ДЛЯ VISION РОЗПІЗНАВАННЯ
-- ============================================================================

-- SKU (унікальний код товару) - якщо ще немає
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS sku TEXT UNIQUE;

-- Колір (окремо від назви для фільтрації)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS color TEXT;

-- Тканина (КРИТИЧНО для Vision!)
-- Значення: плюш, бавовна, екошкіра, поплін, трикотаж
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS fabric_type TEXT;

-- Тип застібки (КРИТИЧНО для розрізнення Мрія/Лагуна!)
-- Значення: half_zip, full_zip, no_zip, buttons
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS closure_type TEXT;

-- Чи є капюшон (КРИТИЧНО для розрізнення Ритм/Каприз!)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS has_hood BOOLEAN DEFAULT false;

-- Тип штанів
-- Значення: joggers, palazzo, classic, none
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS pants_style TEXT;

-- Особливі ознаки (для унікальної ідентифікації)
-- Наприклад: "лампаси", "смужка", "оборки"
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS special_features TEXT[];

-- Візуальні маркери для Vision (JSON з детальним описом)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS visual_markers JSONB;

-- Як виглядає ззаду (для фото зі спини)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS back_view_description TEXT;

-- Підказки для розпізнавання
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS recognition_tips TEXT[];

-- З чим можна сплутати (для confusion prevention)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS confused_with TEXT[];

-- Фото URL (якщо ще немає)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS photo_url TEXT;

-- Наявність на складі
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS in_stock BOOLEAN DEFAULT true;

-- Кількість на складі
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS stock_quantity INTEGER DEFAULT 0;

-- Активний товар (чи показувати)
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;

-- Timestamps
ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE public.products 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();


-- 2. СТВОРЮЄМО TRIGGER ДЛЯ АВТООНОВЛЕННЯ updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_products_updated_at ON public.products;

CREATE TRIGGER update_products_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- 3. СТВОРЮЄМО ІНДЕКСИ ДЛЯ ШВИДКОГО ПОШУКУ
-- ============================================================================

-- Пошук по назві (для search_products)
CREATE INDEX IF NOT EXISTS idx_products_name_trgm 
ON public.products USING gin (name gin_trgm_ops);

-- Пошук по категорії
CREATE INDEX IF NOT EXISTS idx_products_category 
ON public.products (category);

-- Пошук по тканині (для Vision)
CREATE INDEX IF NOT EXISTS idx_products_fabric 
ON public.products (fabric_type);

-- Пошук по кольору
CREATE INDEX IF NOT EXISTS idx_products_color 
ON public.products (color);

-- Фільтр активних товарів
CREATE INDEX IF NOT EXISTS idx_products_active 
ON public.products (is_active) WHERE is_active = true;

-- Фільтр в наявності
CREATE INDEX IF NOT EXISTS idx_products_in_stock 
ON public.products (in_stock) WHERE in_stock = true;


-- 4. ВКЛЮЧАЄМО РОЗШИРЕННЯ ДЛЯ ПОВНОТЕКСТОВОГО ПОШУКУ
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- 5. СТВОРЮЄМО VIEW ДЛЯ VISION (тільки потрібні дані)
-- ============================================================================

CREATE OR REPLACE VIEW public.products_for_vision AS
SELECT 
    id,
    sku,
    name,
    color,
    category,
    fabric_type,
    closure_type,
    has_hood,
    pants_style,
    special_features,
    visual_markers,
    back_view_description,
    recognition_tips,
    confused_with,
    price,
    sizes,
    photo_url,
    in_stock
FROM public.products
WHERE is_active = true;


-- 6. ПРИКЛАД ОНОВЛЕННЯ ІСНУЮЧОГО ТОВАРУ
-- ============================================================================

-- Приклад для "Костюм Мрія (рожевий)":
/*
UPDATE public.products
SET 
    sku = 'MRIYA-PINK-001',
    color = 'рожевий',
    fabric_type = 'плюш',
    closure_type = 'half_zip',
    has_hood = false,
    pants_style = 'joggers',
    special_features = ARRAY['м''яка тканина', 'ворсистий'],
    visual_markers = '{
        "top": "світшот з half-zip до грудей",
        "bottom": "джогери з манжетами",
        "texture": "плюш - м''який, ворсистий"
    }'::jsonb,
    back_view_description = 'гладка спина без прикрас, тільки шви',
    recognition_tips = ARRAY[
        'ГОЛОВНА ОЗНАКА: half-zip (не повна блискавка!)',
        'Плюшева фактура видна навіть при близькому фото',
        'Манжети на штанах - обов''язкова ознака'
    ],
    confused_with = ARRAY['Костюм Лагуна'],
    photo_url = 'https://example.com/mriya-pink.jpg',
    in_stock = true,
    stock_quantity = 15
WHERE name LIKE '%Мрія%' AND name LIKE '%рожев%';
*/


-- 7. RLS POLICIES (Row Level Security) - ОПЦІОНАЛЬНО
-- ============================================================================

-- Якщо хочеш обмежити доступ:
-- ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY "Allow read for all" ON public.products
--     FOR SELECT USING (true);

-- CREATE POLICY "Allow write for authenticated" ON public.products
--     FOR ALL USING (auth.role() = 'authenticated');
