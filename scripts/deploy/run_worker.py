#!/usr/bin/env python
"""Script to run Celery worker.

Usage:
    # Run all workers
    python scripts/run_worker.py

    # Run specific queue
    python scripts/run_worker.py --queue summarization
    python scripts/run_worker.py --queue followups
    python scripts/run_worker.py --queue crm

    # Run with beat scheduler (for periodic tasks)
    python scripts/run_worker.py --beat

    # Run Flower monitoring (requires flower package)
    python scripts/run_worker.py --flower
"""

import argparse
import subprocess
import sys
from pathlib import Path


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_worker(queue: str | None = None, concurrency: int = 4):
    """Run Celery worker."""
    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.workers.celery_app",
        "worker",
        "--loglevel=INFO",
        f"--concurrency={concurrency}",
    ]

    if queue:
        cmd.extend(["-Q", queue])

    print(f"Starting Celery worker: {' '.join(cmd)}")
    subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)


def run_beat():
    """Run Celery Beat scheduler."""
    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.workers.celery_app",
        "beat",
        "--loglevel=INFO",
    ]

    print(f"Starting Celery Beat: {' '.join(cmd)}")
    subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)


def run_flower():
    """Run Flower monitoring dashboard."""
    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "src.workers.celery_app",
        "flower",
        "--port=5555",
    ]

    print(f"Starting Flower: {' '.join(cmd)}")
    print("Dashboard available at: http://localhost:5555")
    subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Run Celery components")
    parser.add_argument(
        "--queue",
        "-Q",
        help="Specific queue to process (summarization, followups, crm)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=4,
        help="Number of worker processes (default: 4)",
    )
    parser.add_argument(
        "--beat",
        "-B",
        action="store_true",
        help="Run Beat scheduler instead of worker",
    )
    parser.add_argument(
        "--flower",
        "-F",
        action="store_true",
        help="Run Flower monitoring dashboard",
    )

    args = parser.parse_args()

    if args.beat:
        run_beat()
    elif args.flower:
        run_flower()
    else:
        run_worker(queue=args.queue, concurrency=args.concurrency)


if __name__ == "__main__":
    main()
