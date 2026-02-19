# MIRT AI Scripts

This directory contains utility scripts for running, managing, and maintaining the MIRT AI application.

## 🏗️ Production Scripts (The "Holy 4")

These scripts are critical for the production environment and are used in the Docker container and Railway deployment.

| Script | Description | Usage |
|--------|-------------|-------|
| **`run_worker.py`** | **Celery Worker Entrypoint**. Starts the Celery worker process to handle background tasks. Validates Redis connection on startup. | `python scripts/run_worker.py` |
| **`run_beat.py`** | **Celery Beat Entrypoint**. Starts the Celery Beat scheduler for periodic tasks. | `python scripts/run_beat.py` |
| **`run_db_migration.py`** | **Database Migration Runner**. Executes SQL migrations against the configured database. Used in deploy pipelines. | `python scripts/run_db_migration.py` |
| **`sync_products_master_to_db.py`** | **Catalog Synchronizer**. The **Single Source of Truth** for product data. Syncs `data/vision/products_master.yaml` to the PostgreSQL database. | `python scripts/sync_products_master_to_db.py` |

## 🛠️ Development & Utility

| Script | Description | Usage |
|--------|-------------|-------|
| `start_telegram_bot.ps1` | PowerShell helper to start the bot locally with Ngrok checking. | `.\scripts\start_telegram_bot.ps1` |
| `generate_vision_artifacts.py` | Helper to generate Vision API prompts from configuration. | `python scripts/generate_vision_artifacts.py` |
| `run_regression_gate.py` | Local regression gate: validates Python baseline, dependency manifest alignment, lint availability, and critical pytest suites. | `python scripts/run_regression_gate.py --quick` or `python scripts/run_regression_gate.py` |

## 🗄️ Archive

The `scripts/archive/` directory contains legacy scripts, one-off dumps, and old tests that have been retired from the active codebase. If you need to find an old scraping script or throwaway test, look there.

## 🧪 Tests

Unit and integration tests should be located in the `tests/` directory (at the root of the project), not here.
