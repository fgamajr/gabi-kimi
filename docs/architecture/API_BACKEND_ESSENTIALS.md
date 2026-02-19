# API Backend Essentials

Data: 2026-02-19

## Objetivo
Definir o que é essencial na API durante a fase backend-only e o que pode ser desativado/removido em etapas.

## Essencial (manter)
1. Segurança:
- `POST /api/v1/auth/login`
- JWT bearer + policies (`RequireViewer`, `RequireOperator`)

2. Orquestração de pipeline:
- `POST /api/v1/dashboard/seed`
- `GET /api/v1/dashboard/seed/last`
- `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`
- `GET /api/v1/dashboard/sources/{sourceId}/discovery/last`
- `GET /api/v1/dashboard/sources/{sourceId}/fetch/last`
- `GET /api/v1/dashboard/pipeline/phases`

3. Operação e observabilidade mínima:
- `GET /health`
- `GET /health/ready`
- `GET /api/v1/sources/{sourceId}/links`
- `GET /api/v1/sources/{sourceId}/links/{linkId}`
- DLQ:
  - `GET /api/v1/dlq`
  - `GET /api/v1/dlq/stats`
  - `GET /api/v1/dlq/{id}`
  - `POST /api/v1/dlq/{id}/replay`

## Endpoints removidos no modo backend-only
1. APIs legado/mirror de dashboard:
- `/api/v1/stats`
- `/api/v1/jobs`
- `/api/v1/pipeline`

2. APIs orientadas ao frontend:
- `/api/v1/dashboard/stats`
- `/api/v1/dashboard/jobs`
- `/api/v1/dashboard/pipeline`
- `/api/v1/dashboard/health`
- `/api/v1/dashboard/safra`
- `/api/v1/dashboard/sources/{sourceId}/refresh`

## Estratégia de remoção segura
1. Etapa 1 (concluída):
- remover `Gabi.Web` do `docker-compose`.
- remover endpoints legado/frontend da `Program.cs`.

2. Etapa 2:
- mapear consumo real dos endpoints nos scripts/docs.
- mover qualquer dependência para endpoints essenciais.

3. Etapa 3:
- limpar documentação legada e códigos/DTOs mortos.
- após 1 sprint sem uso real, remover contratos remanescentes.

## Critério de aceite
1. pipeline executa (seed/discovery/fetch/ingest) sem frontend.
2. zero-kelvin roda fim-a-fim usando apenas endpoints essenciais.
3. autenticação e autorização permanecem intactas.
