# GABI Development Scripts (Backend-Only)

Scripts organizados por responsabilidade: **infraestrutura**, **API**, **banco** e **setup**.

## CLI único: `./scripts/dev`

```bash
# setup inicial
./scripts/dev setup

# infraestrutura docker
./scripts/dev infra up
./scripts/dev infra down
./scripts/dev infra destroy

# banco
./scripts/dev db apply
./scripts/dev db status
./scripts/dev db create NomeDaMigration
./scripts/dev db reset

# aplicação (somente API)
./scripts/dev app up
./scripts/dev app start
./scripts/dev app down
./scripts/dev app stop
./scripts/dev app status
./scripts/dev app logs api
```

## Fluxo diário

```text
infra up -> db apply -> app up -> app down -> infra down
```

## Arquivos principais

| Arquivo | Uso |
|---|---|
| `_lib.sh` | Biblioteca comum (paths, cores, validações de dependência). |
| `dev` | Entrada principal para todos os comandos. |
| `setup.sh` | Setup inicial (dotnet + docker + infra + migrations). |
| `infra-up.sh` | Sobe Postgres, Elasticsearch e Redis. |
| `infra-down.sh` | Para containers mantendo volumes. |
| `infra-destroy.sh` | Remove containers e volumes (destrutivo). |
| `app-up.sh` | Sobe API em foreground. |
| `app-start-detached.sh` | Sobe API em background. |
| `app-down.sh` | Para API (foreground). |
| `app-stop.sh` | Para API (background). |
| `app-status.sh` | Mostra status da API e infraestrutura. |
| `app-logs.sh` | Logs da API. |
| `db-migrate.sh` | Comandos de migration (apply/create/status/reset). |

## Dependências

- `setup.sh`: `dotnet`, `docker`.
- `app-*`: `dotnet`.
- `db-migrate.sh`: `dotnet` e infraestrutura ativa.

## Portas

| Serviço | Porta |
|---|---|
| API (.NET) | 5100 |
| PostgreSQL | 5433 |
| Elasticsearch | 9200 |
| Redis | 6379 |

