#!/usr/bin/env python
"""Production-ready Celery Beat scheduler launcher for Railway.

This script:
- Validates Redis connection before starting
- Displays startup banner with configuration
- Lists all scheduled tasks
- Runs Celery Beat with production settings

Usage on Railway:
    Start Command: python scripts/run_beat.py
"""

import logging
import os
import sys
from pathlib import Path

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
    service_name="mirt-ai-beat",
)

logger = logging.getLogger(__name__)


def print_banner():
    """Print startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                  MIRT AI - CELERY BEAT                       ║
║                  Production Scheduler Service                ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)
    logger.info("=" * 60)
    logger.info("MIRT AI - Celery Beat Starting")
    logger.info("=" * 60)


def check_redis():
    """Check Redis connection before starting beat."""
    try:
        import redis
        from src.conf.config import settings

        redis_url = settings.REDIS_URL
        logger.info("Checking Redis connection: %s", redis_url.split("@")[-1] if "@" in redis_url else redis_url)

        r = redis.from_url(redis_url)
        r.ping()
        logger.info("✓ Redis connection: OK")
        return True
    except ImportError:
        logger.error("✗ redis package not installed")
        return False
    except Exception as e:
        logger.error("✗ Redis connection failed: %s", e)
        logger.error("  Beat will start but scheduled tasks may fail. Check REDIS_URL environment variable.")
        return False


def log_configuration():
    """Log beat configuration."""
    from src.conf.config import settings

    logger.info("Configuration:")
    logger.info("  CELERY_ENABLED: %s", settings.CELERY_ENABLED)
    logger.info("  REDIS_URL: %s", "configured" if settings.REDIS_URL else "missing")


def log_scheduled_tasks():
    """Log all scheduled tasks from beat_schedule."""
    from src.workers.celery_app import celery_app

    beat_schedule = celery_app.conf.beat_schedule
    if not beat_schedule:
        logger.warning("No scheduled tasks found in beat_schedule!")
        return

    logger.info("Scheduled Tasks:")
    for task_name, task_config in beat_schedule.items():
        task_path = task_config.get("task", "unknown")
        schedule = task_config.get("schedule", "unknown")
        queue = task_config.get("options", {}).get("queue", "default")
        logger.info("  - %s", task_name)
        logger.info("    Task: %s", task_path)
        logger.info("    Schedule: %s", schedule)
        logger.info("    Queue: %s", queue)


def main():
    """Main entry point for beat."""
    print_banner()
    log_configuration()

    # Check Redis
    redis_ok = check_redis()
    if not redis_ok:
        logger.warning("Redis check failed, but continuing...")

    # Log scheduled tasks
    log_scheduled_tasks()

    logger.info("=" * 60)
    logger.info("Starting Celery Beat scheduler...")
    logger.info("=" * 60)

    # Start beat using subprocess (most reliable for Railway)
    import subprocess

    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.workers.celery_app",
        "beat",
        "--loglevel=INFO",
    ]

    logger.info("Executing: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Beat shutdown requested")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error starting beat: %s", e)
        sys.exit(1)

