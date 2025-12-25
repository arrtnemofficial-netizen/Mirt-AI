#!/usr/bin/env python3
"""
Run SQL schema creation script against PostgreSQL Railway.

Usage:
    python scripts/run_sql_schema.py

Requirements:
    - psycopg installed: pip install 'psycopg[binary]'
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psycopg
except ImportError:
    print("❌ psycopg not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)

# Connection string for Railway PostgreSQL
# Public Railway connection string
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:ZxEqgWqgzcZNvMNwhYykInpyxKDjNitk@switchback.proxy.rlwy.net:30044/railway"
)

SQL_FILE = Path(__file__).parent / "sql" / "create_all_tables_postgresql.sql"


def run_schema_creation():
    """Execute SQL schema creation script."""
    print("=" * 60)
    print("MIRT AI - PostgreSQL Schema Creation")
    print("=" * 60)
    print(f"\n📁 SQL file: {SQL_FILE}")
    print(f"🔗 Database: Railway PostgreSQL")
    print()

    # Read SQL file
    if not SQL_FILE.exists():
        print(f"❌ SQL file not found: {SQL_FILE}")
        sys.exit(1)

    print("📖 Reading SQL file...")
    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print(f"✅ SQL file read ({len(sql_content)} bytes)")
    print()

    # Connect to database
    print("🔌 Connecting to PostgreSQL...")
    try:
        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        sys.exit(1)

    # Execute SQL
    print()
    print("🚀 Executing SQL schema creation...")
    print("   (This may take a few seconds...)")
    print()

    try:
        with conn.cursor() as cur:
            cur.execute(sql_content)
            print("✅ SQL executed successfully!")
    except Exception as e:
        print(f"❌ SQL execution failed: {e}")
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # Verify tables
    print()
    print("🔍 Verifying tables...")
    try:
        conn = psycopg.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = [row[0] for row in cur.fetchall()]
            
            print(f"✅ Found {len(tables)} tables:")
            for table in tables:
                print(f"   - {table}")
    except Exception as e:
        print(f"⚠️  Could not verify tables: {e}")
    finally:
        conn.close()

    print()
    print("=" * 60)
    print("✅ Schema creation complete!")
    print("=" * 60)


if __name__ == "__main__":
    run_schema_creation()

