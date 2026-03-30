#!/bin/sh
set -eu

cd /workspace

exec uvicorn src.dev_converge.main:app \
  --host 0.0.0.0 \
  --port "${DEV_CONVERGE_INTERNAL_PORT:-8000}" \
  --reload \
  --reload-dir /workspace/src/dev_converge \
  --reload-dir /workspace/ops

