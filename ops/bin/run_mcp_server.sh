#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)

python_can_run_mcp() {
  "$1" - <<'PY' >/dev/null 2>&1
import httpx
import mcp
PY
}

if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON_CMD="${PYTHON_BIN}"
elif [ -x "/opt/venv/bin/python" ]; then
  PYTHON_CMD="/opt/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python)"
else
  echo "No Python interpreter found for MCP server" >&2
  exit 1
fi

if python_can_run_mcp "${PYTHON_CMD}"; then
  exec "${PYTHON_CMD}" "${REPO_ROOT}/ops/bin/mcp_es_server.py" "$@"
fi

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -qx 'gabi-kimi-backend'; then
    exec docker exec -i gabi-kimi-backend /opt/venv/bin/python /opt/app/ops/bin/mcp_es_server.py "$@"
  fi
  exec docker compose run --rm backend /opt/venv/bin/python /workspace/ops/bin/mcp_es_server.py "$@"
fi

echo "Python interpreter ${PYTHON_CMD} does not have mcp/httpx installed and Docker is unavailable" >&2
exit 1
