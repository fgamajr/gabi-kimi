#!/bin/sh
set -eu

cd /opt/frontend

npm run build

# Sync to shared volume so backend serves the correct index.html
DIST_SHARED="/workspace/src/frontend/app/dist"
mkdir -p "$DIST_SHARED"
cp -r dist/. "$DIST_SHARED/"

exec /opt/frontend/node_modules/.bin/serve dist -l "${FRONTEND_INTERNAL_PORT:-8080}" --no-clipboard
