# Deploy GABI no Fly.io

## Automático

- **Merge (ou push) para `main`**: o workflow **Deploy** no GitHub Actions executa o CI e, se passar, faz o deploy na ordem:
  1. **gabi-dou-es** (Elasticsearch)
  2. **gabi-dou-worker** (pipeline autónomo)
  3. **gabi-dou-web** (API)
  4. **gabi-dou-frontend** (SPA estática)

- Após cada app, um smoke test valida saúde; em caso de falha, o **rollback automático** do app em causa é tentado e o pipeline para.

## Manual

- **GitHub → Actions → Deploy → Run workflow**  
  Útil para refazer deploy sem novo commit (por exemplo, só alteração de config/secrets).

## Rollback manual

Se precisar reverter um app à release anterior:

```bash
fly releases rollback -a gabi-dou-es
fly releases rollback -a gabi-dou-worker
fly releases rollback -a gabi-dou-web
fly releases rollback -a gabi-dou-frontend
```

## Secrets necessários

- **FLY_API_TOKEN**: `fly tokens create deploy`
- **TELEGRAM_BOT_TOKEN** / **TELEGRAM_CHAT_ID**: para notificações de sucesso/falha do deploy

## Pré-condições

- A âncora [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md) descreve validações pendentes (conectividade `.internal`, first boot, rollback por app). Em ambiente novo, confirme essas condições antes de depender do deploy automático.
