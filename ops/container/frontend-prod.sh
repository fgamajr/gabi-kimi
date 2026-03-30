#!/bin/sh
set -eu

cd /opt/frontend

npm run build

# In dev compose, frontend_dist is mounted at /workspace/src/frontend/app/dist
# while the build outputs to /opt/frontend/dist — copy to sync the shared volume.
# In prod compose, frontend_dist is mounted at /opt/frontend/dist directly, so no copy needed.
DIST_SHARED="/workspace/src/frontend/app/dist"
if [ -d "/workspace" ]; then
  mkdir -p "$DIST_SHARED"
  cp -r dist/. "$DIST_SHARED/"
fi

exec /opt/frontend/node_modules/.bin/serve dist -l "${FRONTEND_INTERNAL_PORT:-8080}" --no-clipboard
