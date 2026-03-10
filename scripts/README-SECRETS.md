# Sincronizar secrets a partir do .env

Dois scripts leem o `.env` (local) e definem só o que cada destino precisa.

## O que vai para onde

| Destino | Variáveis (a partir do .env) |
|---------|------------------------------|
| **GitHub Actions** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (notificações do workflow Deploy). **FLY_API_TOKEN** não está no .env — crie com `fly tokens create deploy` e adicione manualmente em Settings → Secrets. |
| **Fly gabi-dou-web** | `PGPASSWORD`, `GABI_AUTH_SECRET`, `QWEN_API_KEY`, `GABI_API_TOKENS`, `GABI_ADMIN_TOKEN_LABELS` |
| **Fly gabi-dou-worker** | `INLABS_EMAIL` (ou `INLABS_USER`), `INLABS_PASSWORD` (ou `INLABS_PWD`), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENAI_API_KEY`, `EMBED_API_KEY` |

O resto do .env (ES_URL, REDIS_URL, etc.) não vai para GitHub nem para estes scripts: no Fly já está no `fly.toml` ou em env por app.

## Uso

```bash
# 1) GitHub (só TELEGRAM_*). Requer: gh auth login
./scripts/sync-secrets-to-github.sh

# 2) Fly (web + worker). Requer: fly auth login
./scripts/sync-secrets-to-fly.sh
```

Por defeito usam o `.env` na raiz; pode passar outro ficheiro: `./scripts/sync-secrets-to-github.sh .env.production`.

## O que pode faltar no .env

- **PGPASSWORD** — senha do Postgres em produção. Se não tiver no .env, defina à mão:  
  `fly secrets set PGPASSWORD=... -a gabi-dou-web`
- **GABI_AUTH_SECRET** — segredo das sessões (ex.: `openssl rand -hex 32`). Obrigatório em produção para o web.  
  Se não tiver no .env: `fly secrets set GABI_AUTH_SECRET=... -a gabi-dou-web`

Depois de acrescentar ao .env, pode voltar a correr `./scripts/sync-secrets-to-fly.sh`.
