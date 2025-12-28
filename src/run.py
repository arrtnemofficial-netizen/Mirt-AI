"""Production server launcher for MIRT AI.

This script starts the FastAPI webhook server with proper logging and configuration.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging before importing anything else
from src.core.logging import setup_logging

is_production = os.getenv("PUBLIC_BASE_URL", "").strip() != "http://localhost:8000"
is_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    json_format=bool(is_production or is_railway),
    service_name="mirt-ai",
)

logger = logging.getLogger(__name__)


def print_banner():
    """Print startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                  MIRT AI - WEBHOOK SERVER                    ║
║                  Production API Service                      ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)
    logger.info("=" * 60)
    logger.info("MIRT AI Webhooks Server Starting")
    logger.info("=" * 60)


def log_configuration():
    """Log server configuration."""
    from src.conf.config import settings

    port = int(os.environ.get("PORT", "8000"))
    env = settings.SENTRY_ENVIRONMENT.lower() if settings.SENTRY_ENVIRONMENT else "development"
    
    logger.info("Configuration:")
    logger.info("  Port: %s", port)
    logger.info("  Environment: %s", env)
    logger.info("  Public URL: %s", settings.PUBLIC_BASE_URL)
    logger.info("  Database: %s", "configured" if settings.DATABASE_URL else "missing")
    logger.info("  Redis: %s", "configured" if settings.REDIS_URL else "missing")
    logger.info("  Celery: %s", "enabled" if settings.CELERY_ENABLED else "disabled")
    logger.info("  Observability: %s", "enabled" if settings.ENABLE_OBSERVABILITY else "disabled")
    
    # Check Telegram usage
    has_telegram_bot = bool(settings.TELEGRAM_BOT_TOKEN.get_secret_value())
    has_manager_bot = bool(settings.MANAGER_BOT_TOKEN.get_secret_value())
    logger.info("  Telegram Bot: %s", "configured" if has_telegram_bot else "not configured")
    logger.info("  Manager Bot: %s", "configured" if has_manager_bot else "not configured")
    
    if has_telegram_bot and not has_manager_bot:
        logger.warning("  ⚠ Telegram bot configured but manager bot not configured - notifications may fail")


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print_banner()
    log_configuration()

    # Get port from environment variable, default to 8000
    port = int(os.environ.get("PORT", "8000"))

    logger.info("=" * 60)
    logger.info("Starting uvicorn server on port %s...", port)
    logger.info("=" * 60)

    uvicorn.run(
        "src.server.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,  # Use our custom logging setup
    )
