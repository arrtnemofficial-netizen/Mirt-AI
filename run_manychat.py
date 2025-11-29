#!/usr/bin/env python3
"""ManyChat webhook server entry point.

This script starts the FastAPI server with ManyChat webhook support.
Use this for local development or as a standalone ManyChat integration.

Usage:
    python run_manychat.py                    # Default port 8000
    python run_manychat.py --port 8080        # Custom port
    python run_manychat.py --reload           # Auto-reload for dev

Environment Variables:
    MANYCHAT_VERIFY_TOKEN - Token to verify ManyChat requests
    SUPABASE_URL - Supabase project URL
    SUPABASE_API_KEY - Supabase API key
    OPENROUTER_API_KEY - LLM API key
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Run ManyChat webhook server."""
    parser = argparse.ArgumentParser(
        description="Start MIRT AI ManyChat webhook server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_manychat.py                    Start on port 8000
    python run_manychat.py --port 8080        Start on port 8080
    python run_manychat.py --reload           Auto-reload for development
    python run_manychat.py --host 0.0.0.0     Bind to all interfaces

Environment:
    Set MANYCHAT_VERIFY_TOKEN to enable request verification.
    Set SUPABASE_URL and SUPABASE_API_KEY for persistence.
        """,
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Check required environment
    if not os.getenv("OPENROUTER_API_KEY"):
        logging.warning("OPENROUTER_API_KEY not set - LLM calls will fail!")

    if not os.getenv("MANYCHAT_VERIFY_TOKEN"):
        logging.warning("MANYCHAT_VERIFY_TOKEN not set - requests won't be verified!")

    # Print startup info
    print("\n" + "=" * 60)
    print("🤖 MIRT AI ManyChat Webhook Server")
    print("=" * 60)
    print(f"   Host:     {args.host}")
    print(f"   Port:     {args.port}")
    print(f"   Reload:   {args.reload}")
    print(f"   Endpoint: http://{args.host}:{args.port}/webhooks/manychat")
    print("=" * 60 + "\n")

    # Start server
    import uvicorn

    uvicorn.run(
        "src.server.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
