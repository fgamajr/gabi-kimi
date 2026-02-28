#!/usr/bin/env bash
set -euo pipefail

# Queue hygiene for local/dev runs:
# - marks stale job_registry rows stuck in processing as failed
# - releases stale hangfire.jobqueue fetched locks

MODE="dry-run"
STALE_MINUTES="${STALE_MINUTES:-20}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-gabi}"
DB_USER="${DB_USER:-gabi}"
DB_PASSWORD="${DB_PASSWORD:-gabi_dev_password}"

usage() {
  cat <<'EOF'
Usage:
  scripts/queue-hygiene.sh [--dry-run|--apply] [--stale-minutes N]

Examples:
  scripts/queue-hygiene.sh --dry-run
  scripts/queue-hygiene.sh --apply --stale-minutes 15
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --stale-minutes)
      STALE_MINUTES="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! [[ "$STALE_MINUTES" =~ ^[0-9]+$ ]] || [[ "$STALE_MINUTES" -le 0 ]]; then
  echo "Invalid --stale-minutes: $STALE_MINUTES" >&2
  exit 2
fi

psql_cmd() {
  PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
}

echo "[queue-hygiene] mode=$MODE stale_minutes=$STALE_MINUTES db=${DB_HOST}:${DB_PORT}/${DB_NAME}"

if [[ "$MODE" == "dry-run" ]]; then
  psql_cmd -c "
    SELECT COUNT(*) AS stale_processing_jobs
    FROM job_registry
    WHERE \"Status\" = 'processing'
      AND COALESCE(\"StartedAt\", \"CreatedAt\") < NOW() - make_interval(mins => ${STALE_MINUTES});
  "
  psql_cmd -c "
    SELECT COUNT(*) AS stale_fetched_jobqueue
    FROM hangfire.jobqueue
    WHERE fetchedat IS NOT NULL
      AND fetchedat < NOW() - make_interval(mins => ${STALE_MINUTES});
  "
  exit 0
fi

psql_cmd -c "
  WITH stale AS (
    SELECT \"JobId\"
    FROM job_registry
    WHERE \"Status\" = 'processing'
      AND COALESCE(\"StartedAt\", \"CreatedAt\") < NOW() - make_interval(mins => ${STALE_MINUTES})
  )
  UPDATE job_registry j
  SET \"Status\" = 'failed',
      \"CompletedAt\" = NOW(),
      \"ErrorMessage\" = LEFT(
        COALESCE(NULLIF(j.\"ErrorMessage\", '' ) || ' | ', '') ||
        'Recovered by queue-hygiene: stale processing entry',
        2000
      )
  FROM stale s
  WHERE j.\"JobId\" = s.\"JobId\";
"

psql_cmd -c "
  UPDATE hangfire.jobqueue
  SET fetchedat = NULL,
      updatecount = COALESCE(updatecount, 0) + 1
  WHERE fetchedat IS NOT NULL
    AND fetchedat < NOW() - make_interval(mins => ${STALE_MINUTES});
"

psql_cmd -c "
  SELECT
    (SELECT COUNT(*) FROM job_registry WHERE \"Status\" = 'processing') AS processing_jobs_remaining,
    (SELECT COUNT(*) FROM hangfire.jobqueue WHERE fetchedat IS NOT NULL) AS fetched_entries_remaining;
"

echo "[queue-hygiene] apply complete"
