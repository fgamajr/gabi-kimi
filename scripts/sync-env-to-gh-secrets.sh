#!/usr/bin/env bash
# Lê .env e define cada KEY=VALUE como GitHub Secret (Actions).
# Uso: ./scripts/sync-env-to-gh-secrets.sh [.env]
# Requer: gh auth login
set -e
ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Ficheiro não encontrado: $ENV_FILE"
  exit 1
fi
while IFS= read -r line; do
  line="${line%%#*}"
  line="${line// /}"
  [[ -z "$line" ]] && continue
  if [[ "$line" == *=* ]]; then
    name="${line%%=*}"
    value="${line#*=}"
    value="${value%\"}"
    value="${value#\"}"
    echo "Definir secret: $name"
    echo -n "$value" | gh secret set "$name"
  fi
done < "$ENV_FILE"
echo "Concluído."
