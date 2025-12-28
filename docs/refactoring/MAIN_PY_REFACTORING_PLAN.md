# План рефакторинга main.py (1725 строк → модульная структура)

## Текущая ситуация

- `src/server/main.py` - **1725 строк** кода
- Папка `src/server/routers/` существует, но пустая
- Все endpoints определены напрямую в `main.py`

## Структура endpoints в main.py

### Health endpoints (5 штук)
- `GET /health`
- `GET /health/observability`
- `GET /health/memory`
- `GET /health/workers`
- `GET /health/preflight`

### Media (1 штука)
- `GET /media/proxy`

### API v1 (2 штуки)
- `POST /api/v1/messages`
- `POST /api/v1/sitniks/update-status`

### Webhooks ManyChat (3 штуки)
- `POST /webhooks/manychat`
- `POST /webhooks/manychat/followup`
- `POST /webhooks/manychat/create-order`

### Webhooks Sitniks (3 штуки)
- `POST /webhooks/snitkix/order-status`
- `POST /webhooks/snitkix/payment`
- `POST /webhooks/snitkix/inventory`

### Automation (2 штуки)
- `POST /automation/mirt-summarize-prod-v1`
- `POST /automation/mirt-followups-prod-v1`

### Telegram (1 штука, отключен)
- `POST /webhooks/telegram` (отключен по умолчанию)

## План рефакторинга

### 1. Создать роутеры

#### `src/server/routers/__init__.py`
```python
"""FastAPI routers for MIRT AI."""
```

#### `src/server/routers/health.py`
- Все 5 health endpoints
- ~200 строк

#### `src/server/routers/media.py`
- Media proxy endpoint
- ~50 строк

#### `src/server/routers/api.py`
- API v1 endpoints
- ~150 строк

#### `src/server/routers/webhooks_manychat.py`
- ManyChat webhooks
- ~200 строк

#### `src/server/routers/webhooks_sitniks.py`
- Sitniks webhooks
- ~100 строк

#### `src/server/routers/automation.py`
- Automation endpoints
- ~100 строк

#### `src/server/routers/telegram.py` (опционально)
- Telegram webhook (если нужно)
- ~30 строк

### 2. Обновить main.py

**До:**
```python
@app.get("/health")
async def health() -> dict[str, Any]:
    ...

@app.post("/api/v1/messages")
async def api_v1_messages(...):
    ...
```

**После:**
```python
from src.server.routers import (
    health,
    media,
    api,
    webhooks_manychat,
    webhooks_sitniks,
    automation,
)

app.include_router(health.router, tags=["health"])
app.include_router(media.router, tags=["media"])
app.include_router(api.router, prefix="/api/v1", tags=["api"])
app.include_router(webhooks_manychat.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(webhooks_sitniks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(automation.router, prefix="/automation", tags=["automation"])
```

### 3. Структура файлов после рефакторинга

```
src/server/
├── main.py                    # ~300 строк (lifespan, app setup, middleware)
├── routers/
│   ├── __init__.py
│   ├── health.py              # ~200 строк
│   ├── media.py               # ~50 строк
│   ├── api.py                 # ~150 строк
│   ├── webhooks_manychat.py   # ~200 строк
│   ├── webhooks_sitniks.py    # ~100 строк
│   └── automation.py          # ~100 строк
├── dependencies.py            # (без изменений)
└── middleware.py              # (без изменений)
```

**Итого:** `main.py` уменьшится с **1725 строк до ~300 строк**

## Преимущества

1. **Читаемость** - каждый роутер отвечает за свою область
2. **Поддерживаемость** - легче найти и изменить нужный endpoint
3. **Тестируемость** - можно тестировать роутеры отдельно
4. **Масштабируемость** - легко добавлять новые роутеры

## Порядок выполнения

1. ✅ Создать `routers/__init__.py`
2. ✅ Создать `routers/health.py` и перенести все health endpoints
3. ✅ Создать `routers/media.py` и перенести media proxy
4. ✅ Создать `routers/api.py` и перенести API v1 endpoints
5. ✅ Создать `routers/webhooks_manychat.py` и перенести ManyChat webhooks
6. ✅ Создать `routers/webhooks_sitniks.py` и перенести Sitniks webhooks
7. ✅ Создать `routers/automation.py` и перенести automation endpoints
8. ✅ Обновить `main.py` - удалить endpoints, добавить `include_router`
9. ✅ Проверить, что все работает (тесты, запуск)

## Важные моменты

- **Импорты** - все зависимости (settings, logger, etc.) должны быть доступны в роутерах
- **Общие модели** - можно вынести в `src/server/models/` если нужно
- **Обратная совместимость** - URL endpoints не должны измениться
- **Telegram webhook** - оставить в `main.py` или создать отдельный роутер (он отключен по умолчанию)

## Пример структуры роутера

```python
"""Health check endpoints."""

from fastapi import APIRouter
from typing import Any

from src.conf.config import settings

router = APIRouter()

@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    ...

@router.get("/health/preflight")
async def health_preflight() -> dict[str, Any]:
    """Comprehensive preflight check."""
    ...
```


