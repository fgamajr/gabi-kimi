#!/bin/sh
set -eu

cd /opt/frontend

npm run build

exec /opt/frontend/node_modules/.bin/serve dist -l "${FRONTEND_INTERNAL_PORT:-8080}" --no-clipboard
