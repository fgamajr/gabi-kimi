#!/bin/bash
echo "🚀 Starting GABI API Server..."
cd "$(dirname "$0")"
export PYTHONPATH=src:$PYTHONPATH
export $(cat .env | grep -v '^#' | xargs)
exec uvicorn gabi.main:app --host 0.0.0.0 --port 8000 --reload --workers 1
