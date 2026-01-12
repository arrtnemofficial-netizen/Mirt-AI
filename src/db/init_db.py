"""
Database Initialization Script
==============================
Initializes the entire database schema from SQL files in src/db.
Also sets up LangGraph checkpoint tables via PostgresSaver.

Usage:
    python src/db/init_db.py

Requirements:
    - DATABASE_URL environment variable must be set.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parents[2]))

try:
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
except ImportError:
    print("❌ Error: Missing dependencies. Run: pip install psycopg[binary] langgraph-checkpoint-postgres")
    sys.exit(1)

from src.conf.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent
SCHEMA_FILES = [
    "schema.sql",                # Products, Orders
    "memory_schema.sql",         # Memories, Profiles
    "agent_sessions.sql",        # Session Store
    "users.sql",                 # User Registry
    "webhook_dedupe_schema.sql", # Webhook Deduplication
    "migrations/20241205_create_llm_traces.sql", # Trace table
    "migrations/20260111_add_detailed_costs.sql", # Cost columns
]

async def init_db():
    """Initialize database tables and extensions."""
    
    db_url = settings.DATABASE_URL
    if not db_url:
        logger.error("❌ DATABASE_URL is not set!")
        sys.exit(1)
        
    logger.info("🚀 Starting database initialization...")
    
    # 1. Execute SQL Schema Files
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Enable vector extension first
                logger.info("📦 Enabling pgvector extension...")
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                
                for filename in SCHEMA_FILES:
                    file_path = DB_DIR / filename
                    if not file_path.exists():
                        logger.warning(f"⚠️ Skipping missing file: {filename}")
                        continue
                        
                    logger.info(f"📜 Executing {filename}...")
                    sql = file_path.read_text(encoding="utf-8")
                    cur.execute(sql)
                    
        logger.info("✅ SQL schemas applied successfully.")
        
    except Exception as e:
        logger.error(f"❌ SQL Execution Failed: {e}")
        sys.exit(1)

    # 2. Initialize LangGraph Checkpointer Tables
    # PostgresSaver automatically creates its tables (checkpoints, writes, etc.) on setup()
    logger.info("⚙️ Initializing LangGraph checkpoint tables...")
    try:
        with psycopg.connect(db_url, autocommit=True, prepare_threshold=None) as conn:
            checkpointer = PostgresSaver(conn)
            checkpointer.setup()
            logger.info("✅ LangGraph tables ready (checkpoints, writes, blobs).")
    except Exception as e:
        logger.error(f"❌ LangGraph Setup Failed: {e}")
        # Not fatal if SQL schemas succeeded, but warning needed
    
    logger.info("\n🎉 DATABASE INITIALIZATION COMPLETE! 🎉")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(init_db())
