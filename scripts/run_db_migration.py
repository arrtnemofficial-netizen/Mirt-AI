#!/usr/bin/env python3
"""
Run database migration script against Supabase/Postgres.

Usage:
    python scripts/run_db_migration.py

Requirements:
    - DATABASE_URL in .env (direct Postgres connection string)
    - Or: Set DATABASE_URL env var before running

To get DATABASE_URL from Supabase:
    1. Go to Supabase Dashboard -> Settings -> Database
    2. Copy "Connection string" (URI format)
    3. Add to .env: DATABASE_URL=postgresql://postgres:PASSWORD@db.PROJECT.supabase.co:5432/postgres
"""

import os
import sys
from pathlib import Path


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psycopg
except ImportError:
    print("❌ psycopg not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)

from dotenv import load_dotenv


# Load .env
load_dotenv()


def get_database_url() -> str | None:
    """Get DATABASE_URL from environment."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Try to construct from Supabase settings
    supabase_url = os.getenv("SUPABASE_URL", "")
    if supabase_url and "supabase.co" in supabase_url:
        # Extract project ref from URL
        # https://abc123.supabase.co -> abc123
        project_ref = supabase_url.replace("https://", "").split(".")[0]
        print("⚠️  DATABASE_URL not set.")
        print("")
        print("To get it from Supabase:")
        print(f"  1. Go to: https://supabase.com/dashboard/project/{project_ref}/settings/database")
        print("  2. Copy 'Connection string' (URI format)")
        print(
            f"  3. Add to .env: DATABASE_URL=postgresql://postgres:PASSWORD@db.{project_ref}.supabase.co:5432/postgres"
        )
        print("")
    return None


def run_migration(database_url: str, sql_file: Path) -> bool:
    """Execute SQL migration file."""
    print(f"📄 Reading migration: {sql_file.name}")

    sql_content = sql_file.read_text(encoding="utf-8")

    print("🔌 Connecting to database...")

    try:
        # psycopg v3 API
        with psycopg.connect(database_url, autocommit=True) as conn:
            # Enable notices
            notices: list[str] = []

            def notice_handler(diag: psycopg.errors.Diagnostic) -> None:
                if diag.message_primary:
                    notices.append(diag.message_primary)

            conn.add_notice_handler(notice_handler)

            print(f"🚀 Running migration ({len(sql_content)} chars)...")

            # Execute the entire SQL file
            conn.execute(sql_content)

            # Print notices
            if notices:
                print("\n📋 Migration output:")
                for notice in notices:
                    print(f"   {notice}")

            print("\n✅ Migration completed successfully!")
            return True

    except psycopg.Error as e:
        print(f"\n❌ Database error: {e}")
        if hasattr(e, "diag") and e.diag:
            if e.diag.message_detail:
                print(f"   Details: {e.diag.message_detail}")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("MIRT AI - Database Migration Runner")
    print("=" * 60)
    print()

    # Get database URL
    database_url = get_database_url()
    if not database_url:
        print("❌ DATABASE_URL not configured. See instructions above.")
        sys.exit(1)

    # Mask password in output
    masked_url = database_url
    if "@" in database_url and ":" in database_url:
        # postgresql://user:password@host -> postgresql://user:***@host
        parts = database_url.split("@")
        if len(parts) == 2:
            prefix = parts[0]
            if ":" in prefix:
                user_part = prefix.rsplit(":", 1)[0]
                masked_url = f"{user_part}:***@{parts[1]}"

    print(f"🔗 Database: {masked_url[:80]}...")
    print()

    # Find migration file
    script_dir = Path(__file__).parent
    migration_file = script_dir / "sql" / "migrate_to_current.sql"

    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        sys.exit(1)

    # Confirm
    print("⚠️  This will modify your database!")
    print(f"   Migration: {migration_file.name}")
    print()
    response = input("Continue? [y/N]: ").strip().lower()

    if response != "y":
        print("Cancelled.")
        sys.exit(0)

    print()

    # Run migration
    success = run_migration(database_url, migration_file)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
