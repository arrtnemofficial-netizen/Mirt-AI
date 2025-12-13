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


-- ============================================================================
-- 8. MEMORY SYSTEM TABLES (Titans-like 3-layer memory)
-- ============================================================================
-- Детальна схема в: src/db/memory_schema.sql
-- Нижче — скорочена версія для швидкого старту.

-- Включаємо pgvector для semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- 8.1. Persistent Memory (профілі користувачів)
CREATE TABLE IF NOT EXISTS public.mirt_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT UNIQUE NOT NULL,
    channel TEXT DEFAULT 'telegram',
    
    -- Child info
    child_profile JSONB DEFAULT '{}',      -- {name, height, age, sizes}
    style_preferences JSONB DEFAULT '{}',  -- {colors, categories, brands}
    
    -- Logistics
    logistics JSONB DEFAULT '{}',          -- {city, nova_poshta, phone}
    
    -- Commerce
    commerce JSONB DEFAULT '{}',           -- {total_orders, avg_order, last_order}
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8.2. Fluid Memory (атомарні факти)
CREATE TABLE IF NOT EXISTS public.mirt_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES public.mirt_profiles(user_id) ON DELETE CASCADE,
    
    fact TEXT NOT NULL,                    -- "Дитина зріст 140 см"
    category TEXT,                         -- child_info, preferences, logistics, etc.
    
    importance FLOAT DEFAULT 0.5,          -- 0.0-1.0, gating threshold 0.6
    surprise FLOAT DEFAULT 0.5,            -- 0.0-1.0, gating threshold 0.4
    
    embedding vector(1536),                -- OpenAI ada-002 embedding
    
    source_message_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON public.mirt_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON public.mirt_memories(importance);

-- 8.3. Compressed Memory (summaries)
CREATE TABLE IF NOT EXISTS public.mirt_memory_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES public.mirt_profiles(user_id) ON DELETE CASCADE,
    
    summary TEXT NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger для auto-update updated_at
CREATE OR REPLACE FUNCTION update_mirt_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_mirt_profiles_updated_at ON public.mirt_profiles;
CREATE TRIGGER update_mirt_profiles_updated_at
    BEFORE UPDATE ON public.mirt_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_mirt_profiles_updated_at();
