#!/bin/sh
set -eu

cd /opt/app

exec uvicorn src.dev_converge.main:app \
  --host 0.0.0.0 \
  --port "${DEV_CONVERGE_INTERNAL_PORT:-8000}" \
  --no-server-header \
  --proxy-headers \
  --forwarded-allow-ips="*"

