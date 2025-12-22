"""Routers package for MIRT AI server.

This package contains all FastAPI routers extracted from main.py
to follow Single Responsibility Principle.
"""

from src.server.routers.api_v1 import router as api_v1_router
from src.server.routers.automation import router as automation_router
from src.server.routers.crm import sitniks_router, snitkix_router
from src.server.routers.health import router as health_router
from src.server.routers.manychat import router as manychat_router
from src.server.routers.media import router as media_router
from src.server.routers.telegram import router as telegram_router

__all__ = [
    "api_v1_router",
    "automation_router",
    "health_router",
    "manychat_router",
    "media_router",
    "sitniks_router",
    "snitkix_router",
    "telegram_router",
]


