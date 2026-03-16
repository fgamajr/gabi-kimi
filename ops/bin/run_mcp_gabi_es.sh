#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/docker-compose.yml"

docker compose -f "${compose_file}" up -d mongo elasticsearch backend >/dev/null

exec docker compose -f "${compose_file}" exec -T backend python ops/bin/mcp_es_server.py "$@"
