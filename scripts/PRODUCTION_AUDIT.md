# Production Scripts Architecture & Cleanup Plan

## 🏗️ Production Architecture (The "Holy 4")

Ці скрипти — єдині, що мають право жити в `scripts/` на продакшені. Вони є частиною runtime або deploy pipeline.

| Script | Role | Production Usage |
|--------|------|------------------|
| **`run_worker.py`** | **Worker Entrypoint** | Запускається Railway Worker Service. Обробляє Celery tasks. |
| **`run_beat.py`** | **Scheduler Entrypoint** | Запускається Railway Beat Service. Планує періодичні задачі. |
| **`run_db_migration.py`** | **DB Migration** | Виконується під час деплою (Deploy Step) для накату схеми SQL. |
| **`sync_products_master_to_db.py`** | **Catalog Sync** | SSOT (Single Source of Truth) для продуктів. Сінхає `products_master.yaml` -> DB. |

### 🛠️ Development Utilities (Keep for convenience)
*   `start_telegram_bot.ps1` (Для локального запуску)
*   `generate_vision_artifacts.py` (Генерація промптів Vision - part of build process?)

---

## 🗑️ The Kill List (Candidate for Deletion)

Ці файли я пропоную видалити (або перемістити в `scripts/archive/` якщо ви параноїк). Вони **НЕ** використовуються в продакшені.

### 1. Old Scrapers & Dumps (Legacy)
Ви сказали, що ми використовуємо `products_master.yaml`. Скрапери більше не потрібні в Runtime.
*   `dump_by_category.py` (One-off CRM dump)
*   `dump_active_only.py`
*   `dump_clean_tree.py`
*   `dump_sitniks_products.py`
*   `scrape_sitniks_optimized.py`
*   `clean_sitniks_data.py`
*   `catalog_to_csv.py`
*   `add_product.py` (Manual helper)

### 2. "Probe" & "Check" Scripts (Ad-hoc Debugging)
Ручні перевірки, які не є частиною CI/CD.
*   `check_all_products.py`
*   `check_schema.py`
*   `check_sitniks_count.py`
*   `delete_webhook.py`
*   `explore_sitniks_products.py`
*   `probe_api.py`
*   `probe_filters.py`
*   `quick_test_prices.py`
*   `verify_snippets.py`
*   `fetch_category_tree.py`
*   `infer_tree.py`

### 3. Manual Tests (Not Pytest)
Тести, які треба було б переписати в `pytest` або видалити.
*   `test_async_graph.py`
*   `test_langgraph_full.py` (23KB! Якщо там є цінна логіка, їй місце в `tests/`, не в `scripts/`)
*   `test_postgres_stores.py`
*   `test_price_by_size.py`
*   `test_prod_tables.py`
*   `test_real_api.py` (21KB!)
*   `test_sitniks_api*.py` (Всі версії)
*   `test_workers.py`
*   `test_workers_real.py`
*   `run_memory_tests.py`

### 4. Redundant / Backup files
*   `run_migration.py` (Дублікат `run_db_migration.py`?)
*   `run_sql_schema.py`
*   `run_sql_schema_railway.sh`
*   `migrate_add_price_by_size.sql` (Має бути в `scripts/sql/`)
*   `supabase_analysis.json` (Старий файл)

## 📋 Action Plan
1.  **Move** `migrate_add_price_by_size.sql` -> `scripts/sql/archive/`.
2.  **Delete** Group 1 (Scrapers) immediately.
3.  **Delete** Group 2 (Probes) immediately.
4.  **Review** Group 3 (Tests): Move `test_real_api.py` and `test_langgraph_full.py` to `tests/manual/` if you want to keep them, otherwise DELETE.
5.  **Delete** Group 4 (Redundant).

---
**Ready to execute deletion? Say "DELETE ALL TRASH" to proceed with full cleanup.**
