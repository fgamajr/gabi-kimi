#!/bin/sh
set -eu

cd /opt/app

exec uvicorn src.backend.main:app \
  --host 0.0.0.0 \
  --port "${BACKEND_INTERNAL_PORT:-8000}" \
  --no-server-header \
  --proxy-headers \
  --forwarded-allow-ips="*"
