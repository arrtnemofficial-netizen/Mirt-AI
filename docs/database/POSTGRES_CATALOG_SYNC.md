# Документація: Синхронізація каталогу в PostgreSQL

Цей документ описує, як одним запуском залити весь каталог товарів у будь‑який PostgreSQL, використовуючи `products_master.yaml` як єдине джерело правди.

## 1) Де скрипт
Скрипт для синхронізації:
`scripts/sync_products_master_to_db.py`

## 2) Як залити в інший PostgreSQL
1) Встанови `DATABASE_URL`  
2) Запусти скрипт

Приклад:
```powershell
$env:DATABASE_URL="postgresql://USER:PASS@HOST:PORT/DB"
python scripts/sync_products_master_to_db.py
```

## 3) Що робить скрипт
- створює колонку `price_by_size`, якщо її ще нема
- видаляє колонку `price` (за замовчуванням, бо ціна по розмірах важливіша)
- оновлює існуючі SKU з `products_master.yaml`
- може додати відсутні SKU (опція `--insert-missing`)

## 4) Додаткові опції
Додати відсутні SKU:
```powershell
python scripts/sync_products_master_to_db.py --insert-missing
```

Не видаляти колонку `price`:
```powershell
python scripts/sync_products_master_to_db.py --no-drop-price
```

## 5) Єдине джерело правди (SSOT)
Єдине джерело правди для товарів:
`data/vision/products_master.yaml`

Правильний цикл:
1) Редагуєш `products_master.yaml`
2) Запускаєш `sync_products_master_to_db.py`
3) Сервіси читають актуальні дані з PostgreSQL

## 6) Перевірка після синхронізації
Переконайся, що дані оновились:
```sql
SELECT COUNT(*) FROM public.products;
SELECT sku, sizes, colors, price_by_size FROM public.products LIMIT 10;
```

## 7) Важливо
Не редагуй дані напряму в БД, якщо хочеш уникнути конфліктів.  
Правки роби в `products_master.yaml`, а потім синхронізуй скриптом.
