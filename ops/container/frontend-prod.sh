#!/bin/sh
set -eu

cd /opt/frontend

npm run build

exec npm run preview -- --host 0.0.0.0 --port "${FRONTEND_INTERNAL_PORT:-8080}"
