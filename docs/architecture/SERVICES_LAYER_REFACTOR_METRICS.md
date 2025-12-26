# Services Layer Refactor Metrics

This document defines success and failure metrics for the services-layer reorganization.

## Success Metrics

- `imports_updated`: All internal imports resolve to new package paths without fallback shims.
- `smoke_pass`: `python -m pytest tests/smoke -q` passes.
- `critical_integration_pass`: `python -m pytest tests/integration/test_memory_e2e.py -q` passes.
- `no_shadowed_modules`: No file/dir name collisions (file + package with same name).
- `no_dead_packages`: No empty placeholder packages left in `src/services/`.
- `runtime_startup_ok`: App boots and logs successful startup without ImportError.

## Failure Metrics ("Proeb")

- `import_error`: Any `ModuleNotFoundError` or `ImportError` at startup.
- `circular_import`: Import cycle causing partially-initialized modules.
- `smoke_fail`: Any failure in `tests/smoke`.
- `integration_fail`: Failure in `tests/integration/test_memory_e2e.py`.
- `runtime_fallback`: Unintended fallback to in-memory stores due to bad imports.
- `missing_export`: Service API missing from new package `__init__.py`.

## Validation Checklist

- `rg -n "src\.services\.(catalog_service|order_service|message_store|postgres_pool)" src tests` returns no matches.
- `rg -n "src\.services\.storage" src` returns expected new imports only.
- `python -m pytest tests/smoke -q`.
- `python -m pytest tests/integration/test_memory_e2e.py -q`.

## Rollback Trigger

- Any `import_error` or `smoke_fail` in production indicates immediate rollback.
