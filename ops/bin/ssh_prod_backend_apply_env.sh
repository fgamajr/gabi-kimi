#!/usr/bin/env bash
# Da tua máquina: força recriação do backend em produção para aplicar .env (sem depender de git pull no servidor).
# Exige: Host gabi-prod no ~/.ssh/config (ou GABI_SSH_HOST).
set -euo pipefail
HOST="${GABI_SSH_HOST:-gabi-prod}"
DIR="${GABI_PROD_DIR:-/home/gabi/gabi-kimi}"
ssh -o BatchMode=yes "$HOST" bash -s <<EOF
set -euo pipefail
cd "$DIR"
if [[ -f docker-compose.yml && -f docker-compose.prod.yml ]]; then
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend --force-recreate
else
  docker compose -f docker-compose.prod.yml up -d backend --force-recreate
fi
echo "Backend recriado. RAG_ENABLED no container:"
docker exec gabi-kimi-backend env | grep '^RAG_ENABLED=' || true
EOF
