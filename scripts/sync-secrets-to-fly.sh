#!/usr/bin/env bash
# Envia para os apps Fly.io os secrets que vêm do .env (por app).
# Uso: ./scripts/sync-secrets-to-fly.sh [.env]
# Requer: fly auth login e estar no diretório do repo
#
# Valores com aspas duplas ou quebras de linha podem dar problema; nesse caso
# defina o secret à mão: fly secrets set NOME=valor -a gabi-dou-web
set -e
ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Ficheiro não encontrado: $ENV_FILE"
  exit 1
fi

get_val() {
  grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | sed 's/^[^=]*=//' | sed 's/^[" ]*//;s/[" ]*$//' | head -1 || true
}

# --- gabi-dou-web ---
echo "gabi-dou-web..."
WEB_ARGS=()
for name in PGPASSWORD GABI_AUTH_SECRET QWEN_API_KEY GABI_API_TOKENS GABI_ADMIN_TOKEN_LABELS; do
  val=$(get_val "$name")
  if [[ -n "$val" ]]; then
    WEB_ARGS+=( "$name=$val" )
  fi
done
if [[ ${#WEB_ARGS[@]} -gt 0 ]]; then
  fly secrets set "${WEB_ARGS[@]}" -a gabi-dou-web
fi

# --- gabi-dou-worker ---
# Código usa INLABS_EMAIL / INLABS_PASSWORD; .env pode ter INLABS_USER / INLABS_PWD
echo "gabi-dou-worker..."
WORKER_ARGS=()
inlabs_email=$(get_val INLABS_EMAIL)
[[ -z "$inlabs_email" ]] && inlabs_email=$(get_val INLABS_USER)
inlabs_password=$(get_val INLABS_PASSWORD)
[[ -z "$inlabs_password" ]] && inlabs_password=$(get_val INLABS_PWD)
[[ -n "$inlabs_email" ]]  && WORKER_ARGS+=( "INLABS_EMAIL=$inlabs_email" )
[[ -n "$inlabs_password" ]] && WORKER_ARGS+=( "INLABS_PASSWORD=$inlabs_password" )
for name in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID OPENAI_API_KEY EMBED_API_KEY; do
  val=$(get_val "$name")
  if [[ -n "$val" ]]; then
    WORKER_ARGS+=( "$name=$val" )
  fi
done
if [[ ${#WORKER_ARGS[@]} -gt 0 ]]; then
  fly secrets set "${WORKER_ARGS[@]}" -a gabi-dou-worker
fi

echo "Concluído."
