#!/bin/bash
# Fix Hangfire schema corruption issue
set -e

echo "=== Fixing Hangfire Schema ==="

export PGPASSWORD="${PGPASSWORD:-gabi_dev_password}"
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5433}"
PG_USER="${PGUSER:-gabi}"
PG_DB="${PGDATABASE:-gabi}"

echo "Dropping and recreating Hangfire schema..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" <<SQL
DROP SCHEMA IF EXISTS hangfire CASCADE;
CREATE SCHEMA hangfire;
GRANT ALL ON SCHEMA hangfire TO $PG_USER;
SQL

echo "✓ Hangfire schema recreated cleanly"
echo ""
echo "Next: Restart API and Worker to let Hangfire reinitialize"
