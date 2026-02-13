# GABI Development Scripts

Scripts organizados por responsabilidade: **infraestrutura**, **aplicações**, **banco** e **setup**. Toda a lógica comum (paths, cores, checagem de dependências) fica em `_lib.sh`; os scripts podem ser usados direto ou via o CLI único `dev`.

## Um comando só: `./scripts/dev`

```bash
# ──────────────────────────────────────────────────
# 🏗  SETUP (primeira vez após clonar)
# ──────────────────────────────────────────────────
./scripts/dev setup             # Instala deps, EF CLI, npm install, .env

# ──────────────────────────────────────────────────
# 🐳 INFRAESTRUTURA (Docker)
# ──────────────────────────────────────────────────
./scripts/dev infra up          # 1. Sobe PostgreSQL, Elastic, Redis
./scripts/dev infra down        # Para containers (mantém dados)
./scripts/dev infra destroy     # Destrói containers + volumes (DESTRUTIVO)

# ──────────────────────────────────────────────────
# 🗄  BANCO DE DADOS (após infra up)
# ──────────────────────────────────────────────────
./scripts/dev db apply          # 2. Aplica migrations existentes
./scripts/dev db status         # Verifica migrations aplicadas
./scripts/dev db create Nome    # Cria NOVA migration (quando o modelo muda)
./scripts/dev db reset          # Reset do banco (DESTRUTIVO)

# ──────────────────────────────────────────────────
# 🚀 APLICAÇÕES (após db apply)
# ──────────────────────────────────────────────────
./scripts/dev app up            # 3. Inicia API (5100) + Web (3000) - foreground
./scripts/dev app start         # Inicia em background (não bloqueia, CI-friendly)
./scripts/dev app down          # Para API + Web (foreground)
./scripts/dev app stop          # Para API + Web (background)
./scripts/dev app status        # Verifica se estão rodando
./scripts/dev app logs [api|web] # Logs em tempo real

# ──────────────────────────────────────────────────
# ℹ️  AJUDA
# ──────────────────────────────────────────────────
./scripts/dev help              # Lista todos os comandos
```

### Fluxo do dia a dia

```
infra up → db apply → app up → (desenvolve) → app down → infra down
```

### Reset total (zero kelvin)

```bash
./scripts/dev app down          # Para apps
./scripts/dev infra destroy     # Destrói tudo (confirma com DESTROY)
./scripts/dev setup             # Reinstala tudo
./scripts/dev infra up          # Sobe Docker
./scripts/dev db apply          # Aplica migrations
./scripts/dev app up            # Sobe API + Web
```

## Estrutura dos arquivos

| Arquivo | Uso |
|---------|-----|
| `_lib.sh` | **Não executar.** Biblioteca compartilhada (ROOT, paths, cores, `check_cmd`, `require_*_deps`). |
| `dev` | CLI único: encaminha para os scripts abaixo. |
| `setup.sh` | Setup inicial: dependências, EF CLI, infra, migrations, npm install, .env. |
| `infra-up.sh` | Sobe PostgreSQL, Elasticsearch, Redis (Docker). |
| `infra-down.sh` | Para containers (volumes preservados). |
| `infra-destroy.sh` | Para containers e **remove volumes** (confirma com `DESTROY`). |
| `app-up.sh` | Inicia API (5100) e Web (3000); bloqueia até Ctrl+C. |
| `app-start-detached.sh` | Inicia API + Web em background (não bloqueia, CI-friendly). |
| `app-down.sh` | Para API e Web (quando rodou com up). |
| `app-stop.sh` | Para API e Web (quando rodou com start). |
| `app-status.sh` | Verifica se apps estão rodando. |
| `app-logs.sh` | `tail -f` dos logs (api | web | all). |
| `db-migrate.sh` | Migrations: apply, create, status, reset (confirma com `RESET`). |

## Dependências

- **setup.sh** exige: **.NET SDK**, **Docker** (daemon rodando), **Node 18+**, **npm**. Se faltar algum, o script lista o que falta e encerra com erro.
- **app-up.sh** exige: **.NET SDK**, **Node 18+**. Infraestrutura deve estar rodando (`infra-up.sh`).
- **infra-up.sh** e **db-migrate.sh apply** checam Docker; **db-migrate.sh** checa `dotnet`.

Paths (projeto Web, API, Postgres, diretório de logs) vêm de `_lib.sh`; para usar outro frontend, ajuste `GABI_WEB_DIR` em `_lib.sh`.

## Modo Foreground vs Background

**Foreground (`app up`):**
- Bloqueia o terminal (você vê os logs)
- Pressione **Ctrl+C** para parar tudo
- Ideal para desenvolvimento diário

**Background (`app start`):**
- Não bloqueia (retorna imediatamente)
- Use `app status` para verificar se estão rodando
- Use `app stop` para parar
- Ideal para CI/CD ou quando precisa rodar outros comandos

## Portas

| Serviço | Porta |
|---------|-------|
| Web (Vite) | 3000 |
| API (.NET) | 5100 |
| PostgreSQL | 5433 |
| Elasticsearch | 9200 |
| Redis | 6379 |

## Logs

Diretório: `$GABI_LOG_DIR` (padrão `/tmp/gabi-logs/`).  
Ver em tempo real: `./scripts/app-logs.sh` ou `./scripts/dev app logs`.

## Troubleshooting

- **Porta ocupada:** `./scripts/app-down.sh` ou `lsof -ti:5100 | xargs kill -9`
- **Banco inconsistente:** `./scripts/db-migrate.sh reset` e depois `apply`
- **Reset total (perde dados):** `./scripts/app-down.sh` → `./scripts/infra-destroy.sh` (confirmar com `DESTROY`) → `./scripts/setup.sh`
- **Node/dotnet não encontrado:** Rodar sempre a partir da raiz do repositório; `setup.sh` e `app-up.sh` checam dependências no início.

## Nota sobre migrations

> As migrations já estão no repositório (`Migrations/InitialPersistence`). `db apply` aplica as existentes. Use `db create Nome` **apenas** quando alterar modelos em `Gabi.Postgres/Entities/`.
