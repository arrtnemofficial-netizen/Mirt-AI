#!/usr/bin/env python3
"""Check database schema for messages and users tables."""

import os
import sys

from dotenv import load_dotenv


load_dotenv()

try:
    import psycopg
except ImportError:
    print("psycopg not installed")
    sys.exit(1)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set")
    sys.exit(1)

conn = psycopg.connect(DATABASE_URL)

print("=" * 50)
print("MESSAGES TABLE (public schema)")
print("=" * 50)
cur = conn.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'messages' AND table_schema = 'public'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]:20} {row[1]:20} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")

print()
print("=" * 50)
print("USERS TABLE (public schema)")
print("=" * 50)
cur = conn.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'users' AND table_schema = 'public'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]:20} {row[1]:20} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")

print()
print("=" * 50)
print("LLM_USAGE TABLE (public schema)")
print("=" * 50)
cur = conn.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'llm_usage' AND table_schema = 'public'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]:20} {row[1]:20} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")

print()
print("=" * 50)
print("MIRT_PROFILES TABLE (public schema)")
print("=" * 50)
cur = conn.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'mirt_profiles' AND table_schema = 'public'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]:20} {row[1]:20} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")

print()
print("=" * 50)
print("MIRT_MEMORIES TABLE (public schema)")
print("=" * 50)
cur = conn.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'mirt_memories' AND table_schema = 'public'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]:20} {row[1]:20} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")

conn.close()
