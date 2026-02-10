# GABI - Gerador Automático de Boletins por Inteligência Artificial

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.2-009688.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-TCU%20Internal-red.svg)]()

## 📋 Visão Geral

O **GABI** é uma plataforma de ingestão, indexação e busca semântica de documentos jurídicos do TCU (Tribunal de Contas da União). Utiliza inteligência artificial para processar, analisar e disponibilizar acesso inteligente a acórdãos, normas internas, súmulas e outras publicações institucionais.

### Funcionalidades Principais

- 🔍 **Busca Híbrida**: Combina BM25 (Elasticsearch) + Similaridade Cosseno (pgvector) com RRF
- 📄 **Ingestão Multi-Fonte**: APIs, crawling web, arquivos CSV/PDF
- 🤖 **Embeddings Semânticos**: Modelo multilingual MiniLM-L12-v2 (384 dimensões)
- ⚡ **Processamento Assíncrono**: Pipeline com Celery + Redis
- 🔐 **Autenticação JWT**: Integração com Keycloak TCU
- 📊 **Observabilidade**: Métricas Prometheus, logs estruturados
- 🔌 **Integração MCP**: Servidor MCP para ChatTCU

## 🏗️ Arquitetura

```
┌─────────────┐     ┌─────────────────────────────────────────┐     ┌─────────────┐
│   Fontes    │────▶│  Discovery → Fetch → Parse → Chunk →   │────▶│   Storage   │
│  TCU/Câmara │     │  Embed → Index                           │     │ PG + ES +   │
└─────────────┘     └─────────────────────────────────────────┘     │ Redis       │
                                                                    └──────┬──────┘
                                                                           │
                    ┌─────────────┐     ┌─────────────┐                   │
                    │   ChatTCU   │◀────│  API/MCP    │◀──────────────────┘
                    └─────────────┘     └─────────────┘
```

### Stack Tecnológica

| Componente | Tecnologia | Versão |
|------------|------------|--------|
| Python | 3.11.x | Core |
| FastAPI | 0.109.2 | API Web |
| SQLAlchemy | 2.0.28 | ORM |
| Alembic | 1.13.1 | Migrations |
| Celery | 5.3.6 | Task Queue |
| PostgreSQL | 15+ | Database |
| pgvector | 0.5.1 | Vetorial |
| Elasticsearch | 8.11.0 | Busca Textual |
| Redis | 7.x | Cache/Broker |
| TEI | 1.4.x | Embeddings |

## 🚀 Instalação

### Pré-requisitos

- Python 3.11+
- Docker e Docker Compose
- PostgreSQL 15+ com extensão pgvector
- Elasticsearch 8.11.0
- Redis 7.x

### Setup Local

```bash
# Clone o repositório
git clone <repo-url>
cd gabi

# Crie o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou: .venv\Scripts\activate  # Windows

# Instale as dependências
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com suas configurações

# Execute as migrations
alembic upgrade head

## Quick Start

```bash
# Setup local environment
make init

# Or manually:
docker compose --profile infra up -d

# Verify installation
curl http://localhost:8000/health
```

### Setup Local (Detalhado)

```bash
# Clone o repositório
git clone <repo-url>
cd gabi

# Crie o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou: .venv\Scripts\activate  # Windows

# Instale as dependências
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com suas configurações

# Execute as migrations
alembic upgrade head

# Inicie os serviços com Docker Compose
docker-compose up -d postgres elasticsearch redis

# Inicie a aplicação
uvicorn src.gabi.main:app --reload
```

### Configuração

As configurações são gerenciadas via variáveis de ambiente (prefixo `GABI_`):

```bash
# Ambiente
GABI_ENVIRONMENT=local
GABI_DEBUG=true
GABI_LOG_LEVEL=info

# PostgreSQL
GABI_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/gabi

# Elasticsearch
GABI_ELASTICSEARCH_URL=http://localhost:9200

# Redis
GABI_REDIS_URL=redis://localhost:6379/0

# TEI (Embeddings)
GABI_TEI_URL=http://localhost:8080

# Auth
GABI_KEYCLOAK_URL=https://auth.tcu.gov.br
GABI_JWKS_CACHE_TTL=300
```

## 📝 Uso

### API REST

```bash
# Health check (also available as /api/v1/health)
curl http://localhost:8000/health

# Busca semântica
curl -X POST "http://localhost:8000/api/v1/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "licitação direta",
    "sources": ["tcu_acordaos"],
    "limit": 10
  }'

# Listar fontes
curl http://localhost:8000/api/v1/sources
```

### CLI

```bash
# Executar pipeline de ingestão para uma fonte
python -m gabi.cli ingest --source tcu_acordaos

# Verificar status das fontes
python -m gabi.cli status

# Reindexar documentos
python -m gabi.cli reindex --source tcu_normas
```

### Workers Celery

```bash
# Iniciar worker
make worker

# Monitorar com Flower
make flower
```

## 🧪 Testes

```bash
# Executar todos os testes
make test

# Testes unitários
pytest tests/unit -v

# Testes de integração
pytest tests/integration -v

# Cobertura
make coverage
```

## 📁 Estrutura do Projeto

```
gabi/
├── src/gabi/           # Código fonte principal
│   ├── api/            # Rotas FastAPI
│   ├── models/         # SQLAlchemy models
│   ├── schemas/        # Pydantic schemas
│   ├── services/       # Lógica de negócio
│   ├── pipeline/       # Ingestão de dados
│   ├── crawler/        # Web crawling
│   ├── auth/           # Autenticação
│   ├── mcp/            # Servidor MCP
│   └── governance/     # Governança de dados
├── tests/              # Testes
├── alembic/            # Migrations
├── k8s/                # Kubernetes manifests
├── docker/             # Dockerfiles
└── scripts/            # Scripts utilitários
```

## 🔧 Comandos Make

```bash
make install      # Instalar dependências
make dev          # Iniciar ambiente de desenvolvimento
make test         # Executar testes
make lint         # Executar linter (ruff)
make format       # Formatar código
make type-check   # Verificar tipos (mypy)
make coverage     # Relatório de cobertura
make build        # Build da imagem Docker
make deploy       # Deploy para Fly.io
```

## 📚 Documentação

- [Especificação Técnica](docs/GABI_SPECS_FINAL_v1.md)
- [Configuração de Fontes](sources.yaml)
- [API Documentation](http://localhost:8000/docs) (OpenAPI/Swagger)

## 🤝 Contribuindo

1. Crie uma branch: `git checkout -b feature/nome-da-feature`
2. Faça commit das alterações: `git commit -am 'Adiciona nova feature'`
3. Push para a branch: `git push origin feature/nome-da-feature`
4. Abra um Pull Request

## 📄 Licença

Uso Interno TCU - Restrito.

---

**Contato**: [tcu.gov.br](https://www.tcu.gov.br)
