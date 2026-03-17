#!/bin/sh
set -eu

cd /workspace

exec uvicorn src.backend.main:app \
  --host 0.0.0.0 \
  --port "${BACKEND_INTERNAL_PORT:-8000}" \
  --reload \
  --reload-dir /workspace/src/backend \
  --reload-dir /workspace/ops
