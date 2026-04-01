#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
compose_file="${COMPOSE_FILE:-docker-compose.prod.yml}"
batch_size="${RECONCILE_BATCH_SIZE:-5000}"

cd "${repo_root}"
docker compose -f "${compose_file}" up -d mongo elasticsearch backend >/dev/null
docker compose -f "${compose_file}" exec -T backend python -m src.backend.ingest.es_reconcile --batch-size "${batch_size}"
bash "${script_dir}/update_homepage_cache.sh"
