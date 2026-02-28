# Zero Kelvin Checklist (Backend-Only)

Data: 2026-02-19

Checklist operacional para validar rebuild completo do ambiente sem frontend.

## Execução rápida

```bash
./tests/zero-kelvin-test.sh docker-only
```

Opcional (stress):

```bash
./tests/zero-kelvin-test.sh docker-20k --source all --phase full --max-docs 20000 --monitor-memory
```

## Fase 1: destruição completa

| Verificação | Comando | Esperado |
|---|---|---|
| Derrubar stack | `docker compose down -v --remove-orphans` | sem containers do projeto |
| Portas livres | `lsof -i :5100 :5433 :9200 :6380` | nenhuma ocupada |
| Limpar processos API | `pkill -f "dotnet.*Gabi.Api"` | API parada |

## Fase 2: setup

| Verificação | Comando | Esperado |
|---|---|---|
| Subir infra | `./scripts/dev infra up` | postgres/redis/es em up/healthy |
| Build app containers | `docker compose build api worker` | build sem erro |
| Subir API+Worker | `docker compose --profile api --profile worker up -d` | serviços em execução |

## Fase 3: validação funcional mínima

| Verificação | Comando | Esperado |
|---|---|---|
| Health | `curl -s http://localhost:5100/health` | `Healthy` |
| Login | `POST /api/v1/auth/login` | JWT válido |
| Fases pipeline | `GET /api/v1/dashboard/pipeline/phases` | fases seed/discovery/fetch/ingest |
| Seed | `POST /api/v1/dashboard/seed` + `GET /seed/last` | seed concluída |
| Discovery trigger | `POST /api/v1/dashboard/sources/{id}/phases/discovery` | job enfileirado |
| Fetch trigger | `POST /api/v1/dashboard/sources/{id}/phases/fetch` | job enfileirado |

## Endpoints de referência no teste

- `POST /api/v1/auth/login`
- `POST /api/v1/dashboard/seed`
- `GET /api/v1/dashboard/seed/last`
- `GET /api/v1/dashboard/pipeline/phases`
- `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`
- `GET /api/v1/dashboard/sources/{sourceId}/discovery/last`
- `GET /api/v1/dashboard/sources/{sourceId}/fetch/last`
- `GET /api/v1/sources/{sourceId}/links`

## Troubleshooting curto

- Ver logs API: `./scripts/dev app logs api`
- Ver status: `./scripts/dev app status`
- Reaplicar migrations: `./scripts/dev db apply`
- Recuperar fila/processamento zumbi: `scripts/queue-hygiene.sh` e `docs/operations/queue-hygiene.md`
