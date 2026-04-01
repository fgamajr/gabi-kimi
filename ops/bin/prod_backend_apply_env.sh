#!/usr/bin/env bash
# Recria o container backend para aplicar mudanças no .env (restart sozinho não basta).
# Uso no servidor: cd /home/gabi/gabi-kimi && ./ops/bin/prod_backend_apply_env.sh
set -euo pipefail
ROOT="${GABI_PROD_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"
if [[ ! -f docker-compose.prod.yml ]]; then
  echo "erro: execute a partir do repo (docker-compose.prod.yml não encontrado em $ROOT)" >&2
  exit 1
fi
COMPOSE=(docker compose)
[[ -f docker-compose.yml ]] && COMPOSE+=(-f docker-compose.yml -f docker-compose.prod.yml) || COMPOSE+=(-f docker-compose.prod.yml)
echo "Aplicando .env no backend (force-recreate)…"
"${COMPOSE[@]}" up -d backend --force-recreate
echo "OK. Smoke: curl -sS -m 120 -X POST http://127.0.0.1:8001/api/answer -H 'Content-Type: application/json' -d '{\"query\":\"teste\"}' | head -c 200"
