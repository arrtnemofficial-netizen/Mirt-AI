# Документація: Синхронізація каталогу в PostgreSQL

Цей документ описує bootstrap-синхронізацію каталогу в `public.products` з єдиного джерела правди (SSOT).

## 1) SSOT для продуктів

**SSOT-файл:** `data/vision/products_master.yaml`

Усі зміни асортименту виконуються **спочатку в YAML**, а не напряму в таблиці `products`.

Рекомендований цикл:
1. Оновити `data/vision/products_master.yaml`.
2. Запустити bootstrap-синхронізацію.
3. Перевірити дані SQL-запитом у `public.products`.

## 2) Команда запуску bootstrap

1. Встановити `DATABASE_URL`.
2. Запустити скрипт:

```bash
DATABASE_URL="postgresql://USER:PASS@HOST:PORT/DB" \
python scripts/sync_products_master_to_db.py --insert-missing
```

> `--insert-missing` використовується для початкового bootstrap (додавання SKU, яких ще немає в БД).

## 3) Правила мапінгу полів у `public.products`

Скрипт: `scripts/sync_products_master_to_db.py`.

### Мапінг з `products_master.yaml` → `public.products`

- `product.colors.<color>.sku` → `products.sku`
- `product.name + color.display_name|color_name` → `products.name` (формат: `"{product_name} ({display_color})"`)
- `product.category` → `products.category`
- `product.subcategory` → `products.subcategory`
- `color_name` → `products.colors` (масив з 1 елементом для SKU)
- `product.prices_by_size` + `color.sizes` → `products.price_by_size` (JSONB, фільтр за доступними розмірами SKU)
- `color.sizes` (або ключі `prices_by_size`, якщо `sizes` не задано) → `products.sizes`
- `product.colors.<color>.photo_url` → `products.photo_url`
- `product.visual` → `products.visual_rules` (JSONB)
- `product.distinction` → `products.distinction_rules` (JSONB)

### Поведінка синхронізації

- Якщо SKU існує в БД: виконується `UPDATE` полів `sizes/colors/photo_url/price_by_size/visual_rules/distinction_rules`.
- Якщо SKU відсутній:
  - без `--insert-missing` скрипт завершується з помилкою та списком SKU;
  - з `--insert-missing` виконується `INSERT` нового запису.
- За замовчуванням скрипт видаляє legacy-колонку `price` (`--no-drop-price` вимикає це).

## 4) Troubleshooting

### 4.1 Дублікати

Симптоми:
- конфлікти по `sku` під час `INSERT`;
- кілька кольорів в YAML із однаковим `sku`.

Що робити:
1. Перевірити унікальність `sku` у `products_master.yaml`.
2. Перевірити унікальність `sku` у БД:

```sql
SELECT sku, COUNT(*)
FROM public.products
GROUP BY sku
HAVING COUNT(*) > 1;
```

### 4.2 Порожні поля

Симптоми:
- помилки `Missing sku...`, `Missing sizes...`, `Missing prices_by_size...`.

Що робити:
1. Для кожного кольору заповнити `sku`.
2. Переконатися, що в продукті є непорожній `prices_by_size`.
3. Для SKU задати `sizes` або переконатися, що розміри доступні з `prices_by_size`.

### 4.3 Конфлікти SKU / name

Симптоми:
- один і той самий `sku` у YAML відповідає різним назвам/кольорам;
- в БД вже існує `sku` з іншою бізнес-інтерпретацією.

Що робити:
1. Вирівняти канонічну пару `sku ↔ товар/колір` у SSOT-файлі.
2. Перезапустити bootstrap.
3. Верифікувати результат:

```sql
SELECT sku, name, colors, sizes, price_by_size
FROM public.products
ORDER BY sku;
```
