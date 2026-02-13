# GABI - Sistema de Ingestão e Busca Jurídica TCU

Sistema de ingestão, processamento e busca de dados jurídicos do Tribunal de Contas da União.

## 🚀 Quick Start

### Opção 1: Tudo de uma vez (recomendado)

```bash
./scripts/dev-start.sh
```

Isso inicia:
- Infraestrutura Docker (Postgres, Elasticsearch, Redis)
- API (http://localhost:5100)
- Web Frontend (http://localhost:3000)

Pressione `Ctrl+C` para parar tudo.

### Opção 2: Separado (para debugging)

**Terminal 1 - Infra:**
```bash
./scripts/dev-up.sh
```

**Terminal 2 - API:** (sempre a partir da **raiz do repositório**)
```bash
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```
Se a porta 5100 já estiver em uso, mate o processo (`pkill -f "dotnet.*Gabi.Api"`) ou use outra: `--urls "http://localhost:5101"`.

**Terminal 3 - Web:** (requer **Node 18+** — Vite 5 usa top-level await)
```bash
cd web && npm run dev
```
Se aparecer `SyntaxError: Unexpected reserved word` no web.log, atualize o Node: `nvm install 20 && nvm use 20` (ou instale Node 18+).

### Acessos

| Serviço | URL |
|---------|-----|
| Web Frontend | http://localhost:3000 |
| API | http://localhost:5100 |
| Swagger UI | http://localhost:5100/swagger |
| Health Check | http://localhost:5100/health |

### Problemas comuns

- **"Project file does not exist"** — Rode `dotnet run --project src/Gabi.Api` a partir da **raiz do repositório** (`~/dev/gabi-kimi`), não de dentro de `src/Gabi.Api`.
- **"Address already in use" (5100)** — Outra instância da API ou outro processo está na porta. Pare com `pkill -f "dotnet.*Gabi.Api"` ou use outra porta: `dotnet run --project src/Gabi.Api --urls "http://localhost:5101"`.
- **Web para com "Unexpected reserved word" / SyntaxError no web.log** — Vite 5 exige **Node 18+**. Verifique com `node -v`; se for &lt; 18, use `nvm install 20 && nvm use 20` (ou instale Node 18+).

### Parar Tudo

```bash
./scripts/dev-down.sh  # Para infra Docker
pkill -f "dotnet.*Gabi.Api"  # Para API
pkill -f "vite"  # Para Web
```

---

## 🎨 Frontend

O frontend é uma SPA em Vite que consome a API:

| Funcionalidade | Descrição |
|----------------|-----------|
| **Listagem** | Grid de cards com nome, provedor, estratégia e status |
| **Status Badge** | ● Ativo (verde) / ● Inativo (cinza) |
| **Detalhes** | Painel lateral com metadados e links descobertos |
| **Refresh** | Botão "Atualizar" por fonte ou "Atualizar Tudo" |
| **Discovery** | Executa descoberta de URLs em tempo real |

---

## ✅ Infraestrutura Rodando!

Todos os serviços estão **saudáveis** e prontos:

| Serviço          | Host      | Porta | Status                |
|------------------|-----------|-------|----------------------|
| 🐘 PostgreSQL    | localhost | 5433  | accepting connections |
| 🔍 Elasticsearch | localhost | 9200  | healthy              |
| 🔄 Redis         | localhost | 6379  | PONG                 |

### 🧪 Teste rápido:

```bash
# Conectar ao banco
psql postgresql://gabi:gabi_dev_password@localhost:5433/gabi

# Ver ES
curl http://localhost:9200/_cluster/health

# Testar Redis
docker compose exec redis redis-cli ping
```

---

## 📁 Estrutura do Projeto

```
.
├── src/
│   ├── Gabi.Api/            # REST API (Minimal API)
│   ├── Gabi.Contracts/      # Contratos e interfaces
│   ├── Gabi.Discover/       # Motor de discovery
│   ├── Gabi.Ingest/         # Fetch e Parse
│   ├── Gabi.Postgres/       # EF Core + PostgreSQL
│   ├── Gabi.Sync/           # Engine de sync
│   ├── Gabi.Web/            # Frontend SPA (placeholder)
│   └── Gabi.Worker/         # Entry point (Worker Service)
├── tests/                    # Testes
├── web/                      # Frontend Vite (standalone)
│   ├── src/
│   │   ├── components/      # Source list, detail
│   │   ├── api.js           # Client HTTP
│   │   ├── style.css        # Dark theme
│   │   └── main.js          # Entry point
│   ├── package.json
│   └── vite.config.js
├── scripts/                  # Scripts de conveniência
├── docker/
│   └── postgres/init/        # Scripts SQL de inicialização
├── docker-compose.yml        # Infraestrutura + Apps opcionais
├── Dockerfile                # Worker (Fly.io ready)
├── fly.toml                  # Configuração Fly.io
└── sources_v2.yaml           # Configuração das fontes
```

## 🛠️ Tecnologias

### Backend
- **.NET 8** - Plataforma principal
- **Minimal API** - REST API (Gabi.Api)
- **PostgreSQL 15** - Banco de dados (uuid-ossp, pg_trgm)
- **Elasticsearch 8** - Motor de busca
- **Redis 7** - Cache e filas
- **YamlDotNet** - Parser de sources_v2.yaml

### Frontend
- **Vite** - Build tool
- **Vanilla JS** - Sem framework (manter leve)
- **CSS Custom Properties** - Theming

### Infra
- **Docker** - Containerização
- **Fly.io** - Deploy em produção

## 📖 Documentação

- [Docker Setup](DOCKER.md) - Guia completo de Docker
- [Layout de Deploy](docs/infrastructure/DEPLOY_LAYOUT.md) - Dev / staging / prod
- [Deploy Fly.io](docs/infrastructure/FLY_DEPLOY.md) - Apps separados (API + Worker) e checklist
- [Avaliação de Infraestrutura](docs/infrastructure/INFRA_EVALUATION.md) - Veredito, health checks, logging, recomendações
- [Roadmap](roadmap.md) - Progresso do projeto

## 📝 Licença

Projeto privado - TCU
