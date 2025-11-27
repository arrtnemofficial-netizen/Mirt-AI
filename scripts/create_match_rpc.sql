-- =============================================================================
-- RPC функція для семантичного пошуку продуктів MIRT
-- Виконай цей SQL в Supabase → SQL Editor → Run
-- =============================================================================

CREATE OR REPLACE FUNCTION match_mirt_products(
  query_embedding vector(1536),
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id int8,
  name text,
  variant_name text,
  color_variant text,
  category text,
  subcategory text,
  sizes text[],
  material text,
  care text,
  price_uniform bool,
  price_all_sizes int4,
  price_by_size jsonb,
  colors jsonb,
  photo_url text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    p.id,
    p.name,
    p.variant_name,
    p.color_variant,
    p.category,
    p.subcategory,
    p.sizes,
    p.material,
    p.care,
    p.price_uniform,
    p.price_all_sizes,
    p.price_by_size,
    p.colors,
    -- Витягуємо photo_url з colors jsonb
    COALESCE(
      (p.colors -> (SELECT key FROM jsonb_object_keys(p.colors) LIMIT 1) ->> 'photo_url'),
      ''
    ) AS photo_url,
    -- Косинусна подібність (1 - distance)
    1 - (e.embedding <=> query_embedding) AS similarity
  FROM mirt_product_embeddings e
  JOIN mirt_products p ON p.id = e.product_id
  ORDER BY e.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Додай індекс для швидшого пошуку (якщо ще немає)
CREATE INDEX IF NOT EXISTS mirt_embeddings_vector_idx 
ON mirt_product_embeddings 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 10);

-- Перевірка що функція працює
-- SELECT * FROM match_mirt_products(
--   (SELECT embedding FROM mirt_product_embeddings LIMIT 1),
--   3
-- );
