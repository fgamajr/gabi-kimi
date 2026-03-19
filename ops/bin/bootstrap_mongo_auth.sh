#!/usr/bin/env bash

set -euo pipefail

compose_file="${COMPOSE_FILE:-docker-compose.prod.yml}"
db_name="${DB_NAME:-gabi_dou}"
root_user="${MONGO_INITDB_ROOT_USERNAME:?set MONGO_INITDB_ROOT_USERNAME}"
root_password="${MONGO_INITDB_ROOT_PASSWORD:?set MONGO_INITDB_ROOT_PASSWORD}"
app_user="${MONGO_APP_USERNAME:-gabi_app}"
app_password="${MONGO_APP_PASSWORD:?set MONGO_APP_PASSWORD}"

docker compose -f "${compose_file}" exec -T mongo mongosh admin <<EOF
const adminDb = db.getSiblingDB("admin");
if (!adminDb.getUser("${root_user}")) {
  adminDb.createUser({
    user: "${root_user}",
    pwd: "${root_password}",
    roles: [{ role: "root", db: "admin" }]
  });
}

if (!adminDb.getUser("${app_user}")) {
  adminDb.createUser({
    user: "${app_user}",
    pwd: "${app_password}",
    roles: [{ role: "readWrite", db: "${db_name}" }]
  });
}
EOF

printf '%s\n' \
  "Mongo users ensured." \
  "Next steps:" \
  "1. Set MONGO_AUTH_ENABLED=true in .env" \
  "2. Set MONGO_STRING=mongodb://${app_user}:${app_password}@mongo:27017/${db_name}?authSource=admin" \
  "3. Redeploy mongo, backend, and worker with docker compose -f ${compose_file} up -d mongo backend worker"
