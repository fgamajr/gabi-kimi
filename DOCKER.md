# GABI - Docker Setup

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                     DEVELOPMENT SETUP                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🐳 Docker Compose (Infraestrutura)                         │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │  PostgreSQL  │Elasticsearch │    Redis     │             │
│  │   :5433      │   :9200      │   :6379      │             │
│  └──────────────┴──────────────┴──────────────┘             │
│         │              │              │                     │
│         └──────────────┼──────────────┘                     │
│                        │                                    │
│  💻 Host (Sua Máquina) │                                    │
│  ┌─────────────────────┘                                    │
│  │  dotnet run --project src/Gabi.Worker                     │
│  │  • Hot reload ✅                                          │
│  │  • Debugging fácil ✅                                      │
│  │  • IDE integration ✅                                      │
│  └─────────────────────────────────────────────────────────┘
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Iniciar Infraestrutura

```bash
./scripts/dev-up.sh
```

Este comando:
- Sobe PostgreSQL (porta 5433), Elasticsearch (9200) e Redis (6379)
- Aguarda todos os serviços estarem saudáveis
- Mostra instruções de uso

### 2. Rodar a Aplicação

```bash
dotnet run --project src/Gabi.Worker
```

Ou para hot reload:
```bash
dotnet watch --project src/Gabi.Worker
```

### 3. Parar Infraestrutura

```bash
./scripts/dev-down.sh
```

## 🛠️ Comandos Úteis

### Docker Compose

```bash
# Ver status dos containers
docker compose ps

# Ver logs
docker compose logs -f postgres
docker compose logs -f elasticsearch
docker compose logs -f redis

# Restart serviço específico
docker compose restart postgres

# Shell no container
docker compose exec postgres psql -U gabi -d gabi
docker compose exec redis redis-cli
```

### Banco de Dados

```bash
# Acessar PostgreSQL
psql postgresql://gabi:gabi_dev_password@localhost:5433/gabi

# Backup
docker compose exec postgres pg_dump -U gabi gabi > backup.sql

# Restore
docker compose exec -T postgres psql -U gabi gabi < backup.sql
```

### Elasticsearch

```bash
# Health check
curl http://localhost:9200/_cluster/health

# Listar índices
curl http://localhost:9200/_cat/indices
```

## 📁 Estrutura de Arquivos

```
.
├── docker-compose.yml          # Infra: Postgres, ES, Redis + profiles api/web
├── Dockerfile                  # Worker (Fly.io)
├── fly.toml                    # Fly.io: app gabi-worker
├── fly.api.toml                # Fly.io: app gabi-api (deploy --config fly.api.toml)
├── env.example                 # Exemplo de variáveis (cópia para .env)
├── scripts/
│   ├── dev-up.sh              # Inicia infraestrutura
│   └── dev-down.sh            # Para infraestrutura
├── docs/infrastructure/
│   ├── DEPLOY_LAYOUT.md       # Layout dev/staging/prod
│   └── FLY_DEPLOY.md          # Decisão Fly (apps separados) e checklist
└── src/
    ├── Gabi.Api/Dockerfile     # Imagem da API
    └── Gabi.Worker/            # appsettings.* (Dev vs Prod)
```

## Mudanças mínimas (infra)

Ajustes aplicados para alinhar ao layout de deploy e à migração Fly.io:

- **docker-compose:** Removido `container_name` de todos os serviços (evita conflito com múltiplos projetos/paralelismo). Comentário sobre `deploy.resources` (só aplicado em Swarm).
- **Dockerfile (Worker):** Imagem de runtime alterada de `aspnet` para `runtime` (menor; worker não expõe HTTP). Comentário sobre não assar `sources_v2.yaml` em prod quando possível.
- **fly.api.toml:** Criado para o app `gabi-api`; deploy com `fly deploy --config fly.api.toml`.
- **env.example:** Exemplo de variáveis e referência a secrets no Fly.

Detalhes: [docs/infrastructure/DEPLOY_LAYOUT.md](docs/infrastructure/DEPLOY_LAYOUT.md) e [docs/infrastructure/FLY_DEPLOY.md](docs/infrastructure/FLY_DEPLOY.md).

## 🔧 Configurações

### Desenvolvimento (Host)

Arquivo: `src/Gabi.Worker/appsettings.Development.json`

```json
{
  "ConnectionStrings": {
    "Default": "Host=localhost;Port=5433;Database=gabi;..."
  }
}
```

### Produção (Docker/Fly.io)

Arquivo: `src/Gabi.Worker/appsettings.json`

```json
{
  "ConnectionStrings": {
    "Default": "Host=postgres;Port=5432;Database=gabi;..."
  }
}
```

**Nota**: Em produção os serviços se comunicam via Docker network (nomes dos serviços como host).

## ☁️ Deploy Fly.io

### Setup Inicial

```bash
# Login
fly auth login

# Criar app (se ainda não existir)
fly apps create gabi-worker

# Criar banco de dados gerenciado
fly postgres create --name gabi-db

# Configurar secrets
fly secrets set \
  ConnectionStrings__Default="..." \
  GABI_ELASTICSEARCH_URL="..." \
  GABI_REDIS_URL="..."
```

### Deploy

```bash
fly deploy
```

## ⚠️ Troubleshooting

### Porta 5433 já em uso

```bash
# Verificar processo
sudo lsof -i :5433

# Matar processo ou mudar porta no docker compose.yml
```

### Elasticsearch não inicia (vm.max_map_count)

```bash
# Linux
sudo sysctl -w vm.max_map_count=262144

# Mac (Docker Desktop)
docker run --rm --privileged alpine sysctl -w vm.max_map_count=262144
```

### Permissão negada nos scripts

```bash
chmod +x scripts/*.sh
```

### PostgreSQL - Extensões instaladas

O container PostgreSQL inicia com as seguintes extensões pré-instaladas via `docker/postgres/init/01-init.sql`:

- **uuid-ossp** - Geração de UUIDs
- **pg_trgm** - Busca textual por trigramas (fuzzy search)

```bash
# Verificar extensões instaladas
docker compose exec postgres psql -U gabi -d gabi -c "\dx"
```

## 🎯 Benefícios desta Abordagem

| Aspecto | Antes | Agora |
|---------|-------|-------|
| **Setup** | Instalar Postgres, ES, Redis localmente | `docker compose up` |
| **Dev Experience** | Configuração complexa | Hot reload, debugging fácil |
| **Consistência** | "Funciona na minha máquina" | Mesma infra para todos |
| **Fly.io Migration** | Reescrever tudo | Dockerfile já pronto |
| **Isolation** | Conflitos com outros projetos | Containers isolados |

## 🔮 Roadmap

- [ ] Health check dashboard
- [ ] Seeding automático de dados de teste
- [ ] TEI (embeddings) container opcional
- [ ] API REST container
- [ ] PGAdmin container para administração
