#!/bin/bash
# Full DOU ingestion on the host, using only local MongoDB.
# Run from project root: bash ops/run_full_ingest.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${REPO_ROOT}/.venv-ingest"
LOG_DIR="${REPO_ROOT}/ops/data"
LOG_FILE="${LOG_DIR}/ingest_progress.log"
PYTHON_BIN="${INGEST_PYTHON_BIN:-}"
mkdir -p "$LOG_DIR"

if [ -z "$PYTHON_BIN" ]; then
  if [ -x /opt/homebrew/bin/python3 ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "${VENV_DIR}/bin/python" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "${VENV_DIR}/bin/python" -c 'import lxml, pymongo, pydantic_settings, requests' >/dev/null 2>&1; then
  "${VENV_DIR}/bin/pip" install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r ops/requirements-ingest.txt
fi

export PYTHONPATH="${REPO_ROOT}"
export PYTHONUNBUFFERED=1
export MONGO_STRING="${MONGO_STRING:-mongodb://127.0.0.1:27017/gabi_dou}"
export DB_NAME="${DB_NAME:-gabi_dou}"
export PIPELINE_TMP="${PIPELINE_TMP:-${REPO_ROOT}/ops/data/pipeline}"
export DOU_DATA_PATH="${DOU_DATA_PATH:-${REPO_ROOT}/ops/data}"
export ICLOUD_DATA_PATH="${ICLOUD_DATA_PATH:-}"
export RAW_CACHE_PATH="${RAW_CACHE_PATH:-${REPO_ROOT}/ops/data/raw_cache}"
export DOU_MONTH_PARALLELISM="${DOU_MONTH_PARALLELISM:-6}"
export DOU_INGEST_PARALLELISM="${DOU_INGEST_PARALLELISM:-3}"

{
  echo "[$(date)] Starting host-native full ingest"
  echo "[$(date)] MONGO_STRING=${MONGO_STRING}"
  echo "[$(date)] RAW_CACHE_PATH=${RAW_CACHE_PATH}"
  echo "[$(date)] DOU_MONTH_PARALLELISM=${DOU_MONTH_PARALLELISM}"
  echo "[$(date)] DOU_INGEST_PARALLELISM=${DOU_INGEST_PARALLELISM}"
} >> "$LOG_FILE"

exec "${VENV_DIR}/bin/python" ops/full_ingest_host.py "$@" >> "$LOG_FILE" 2>&1
