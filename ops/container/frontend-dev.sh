#!/bin/sh
set -eu

cd /workspace/src/frontend/app

if [ ! -d node_modules ] || [ -z "$(ls -A node_modules 2>/dev/null)" ]; then
  mkdir -p node_modules
  cp -a /opt/frontend/node_modules/. node_modules/
fi

exec npm run dev -- --host 0.0.0.0 --port "${FRONTEND_INTERNAL_PORT:-8080}"
