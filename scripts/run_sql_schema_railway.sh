#!/bin/bash
# Run SQL schema creation in Railway environment
# This script should be run inside Railway or via Railway CLI

set -e

echo "============================================================"
echo "MIRT AI - PostgreSQL Schema Creation (Railway)"
echo "============================================================"
echo ""

# Get DATABASE_URL from Railway environment
if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL not set"
    echo "   Set it in Railway dashboard or use Railway CLI"
    exit 1
fi

echo "🔗 Using DATABASE_URL from Railway environment"
echo ""

# Path to SQL file
SQL_FILE="scripts/sql/create_all_tables_postgresql.sql"

if [ ! -f "$SQL_FILE" ]; then
    echo "❌ SQL file not found: $SQL_FILE"
    exit 1
fi

echo "📖 Reading SQL file: $SQL_FILE"
echo "🚀 Executing SQL schema creation..."
echo ""

# Use psql if available, otherwise use Python
if command -v psql &> /dev/null; then
    echo "Using psql..."
    psql "$DATABASE_URL" -f "$SQL_FILE"
else
    echo "Using Python..."
    python scripts/run_sql_schema.py
fi

echo ""
echo "✅ Schema creation complete!"

