"""Celery workers for background tasks.

This module contains:
- celery_app: Celery application configuration
- tasks: Background tasks for summarization, followups, CRM
"""

from src.workers.celery_app import celery_app


__all__ = ["celery_app"]
