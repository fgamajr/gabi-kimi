#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
compose_file="${COMPOSE_FILE:-docker-compose.prod.yml}"

cd "${repo_root}"
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.search.editorial --update
