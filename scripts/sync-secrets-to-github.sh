#!/usr/bin/env bash
# Define no GitHub Actions apenas os secrets que o workflow Deploy usa.
# Uso: ./scripts/sync-secrets-to-github.sh [.env]
# Requer: gh auth login
# Nota: FLY_API_TOKEN não está no .env — crie com: fly tokens create deploy
#       e adicione manualmente em Settings → Secrets → FLY_API_TOKEN
set -e
ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Ficheiro não encontrado: $ENV_FILE"
  exit 1
fi

get_val() {
  grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | sed 's/^[^=]*=//' | sed 's/^[" ]*//;s/[" ]*$//' | head -1 || true
}

# Secrets usados pelo workflow Deploy (notificações Telegram)
for name in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  val=$(get_val "$name")
  if [[ -n "$val" ]]; then
    echo "Definir GitHub secret: $name"
    echo -n "$val" | gh secret set "$name"
  else
    echo "Ignorar $name (não encontrado em $ENV_FILE)"
  fi
done

echo "Concluído. Lembrete: FLY_API_TOKEN tem de ser definido manualmente (fly tokens create deploy)."
