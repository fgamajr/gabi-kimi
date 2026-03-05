# AGENTS.md — Guia para Agentes de Codificação

> Arquivo de referência para agentes de IA que trabalham no projeto GABI.
> Leia este arquivo completamente antes de fazer qualquer modificação no código.

---

## Visão Geral do Projeto

**GABI** (Gerador Automático de Boletins por Inteligência Artificial) é um pipeline de ingestão em massa de XMLs do **DOU (Diário Oficial da União)** brasileiro. O projeto baixa bundles ZIP mensais da Imprensa Nacional (in.gov.br), parseia XML estruturado, persiste em PostgreSQL com full-text search BM25 e serve via FastAPI + Alpine.js SPA.

| Aspecto | Detalhe |
|---------|---------|
| **Cobertura** | Jan/2002 → presente (289 meses, 851 ZIPs) |
| **Stack** | Python 3.13, PostgreSQL 16, FastAPI, Alpine.js 3, Tailwind CSS |
| **Busca** | BM25 two-pass (ts_rank → BM25 re-rank) + Elasticsearch (opcional) |
| **Cache** | Redis (autocomplete + top searches) |
| **Auditoria** | CRSS-1 Merkle tree commitment scheme |
| **MCP** | Model Context Protocol server para integração com agentes |

---

## Estrutura do Projeto

```
gabi-kimi/
├── ingest/                    # Pipeline de ingestão de XML
│   ├── bulk_pipeline.py       # Orquestrador principal CLI
│   ├── sync_pipeline.py       # Sync incremental via catálogo
│   ├── dou_ingest.py          # Ingestor para schema dou.*
│   ├── xml_parser.py          # Parser XML INLabs → DOUArticle
│   ├── zip_downloader.py      # Download HTTP + extração ZIP
│   ├── html_extractor.py      # NLP: assinaturas, imagens, refs
│   ├── multipart_merger.py    # Merge artigos multi-parte
│   ├── normalizer.py          # DOUArticle → registro de ingestão
│   ├── bm25_indexer.py        # Build/refresh BM25 + CLI search
│   ├── catalog_scraper.py     # Scrape catálogo in.gov.br
│   ├── identity_analyzer.py   # Identity hashing e deduplicação
│   ├── es_indexer.py          # Elasticsearch backfill/sync
│   └── date_selector.py       # Geração de ranges de datas
│
├── dbsync/                    # Gerenciamento declarativo de schema
│   ├── dou_schema.sql         # Schema DOU: 7 tabelas + views
│   ├── bm25_schema.sql        # Okapi BM25: term stats, corpus stats
│   ├── registry_schema.sql    # Schema temporal append-only (registry.*)
│   ├── schema_sync.py         # DDL diff/apply
│   ├── differ.py              # Diff de schemas
│   ├── planner.py             # Planejador de migrações
│   └── registry_ingest.py     # Ingestão no registry
│
├── commitment/                # CRSS-1 commitment scheme
│   ├── crss1.py               # Serialização canônica
│   ├── tree.py                # Merkle tree
│   ├── anchor.py              # Anchoring de cadeia
│   ├── chain.py               # Gerenciamento de cadeia
│   └── verify.py              # Verificação de provas
│
├── search/                    # Adapters de busca (pg/es)
│   ├── adapters.py            # PGSearchAdapter, ESSearchAdapter
│   └── redis_signals.py       # Redis para autocomplete/analytics
│
├── web/                       # Frontend SPA
│   └── index.html             # Alpine.js 3 + Tailwind CSS
│
├── tests/                     # Suite de testes (script-based)
│   ├── test_commitment.py     # Testes CRSS-1 (pure functions)
│   ├── test_bulk_pipeline.py  # Testes do pipeline (135+ assertions)
│   ├── test_dou_ingest.py     # Testes de ingestão (211+ assertions)
│   ├── test_seal_roundtrip.py # Teste end-to-end de sealing
│   └── fixtures/xml_samples/  # Amostras XML reais do DOU
│
├── infra/                     # Infraestrutura Docker
│   ├── infra_manager.py       # CLI para gerenciar containers
│   └── docker-compose.yml     # PG (5433) + ES (9200) + Redis (6380)
│
├── scripts/                   # Automação
│   ├── daily_sync.sh          # Sync diário (cron/systemd)
│   ├── gabi-sync@.service     # Systemd service template
│   └── gabi-sync@.timer       # Systemd timer template
│
├── deploy/                    # Configurações de deploy
│   ├── postgres/              # Fly.io PostgreSQL
│   └── web/                   # Fly.io Web
│
├── data/                      # Dados (gitignored)
│   ├── dou_catalog_registry.json  # Mapeamento mês→folderId
│   └── inlabs/                # ZIPs baixados
│
├── proofs/                    # CRSS-1 anchor chain e vetores de teste
├── config/                    # Configurações de pipeline
├── governance/                # Classificação, dead code reports
└── archive_legacy/            # Módulos arquivados

# Arquivos principais
├── web_server.py              # FastAPI: search, suggest, chat, document
├── mcp_server.py              # MCP server com 4 tools
├── mcp_es_server.py           # MCP server para Elasticsearch
├── commitment_cli.py          # CLI para commitment operations
├── schema_sync.py             # Entry point para schema sync
├── sources_v3.yaml            # Definição de entidades e relações
├── requirements.txt           # Dependências Python
└── .env.example               # Template de variáveis de ambiente
```

---

## Stack Tecnológico

### Backend
- **Python 3.13+** — Linguagem principal
- **FastAPI** — Web framework
- **psycopg2/psycopg** — PostgreSQL driver
- **httpx** — HTTP client async
- **loguru** — Logging estruturado

### Banco de Dados
- **PostgreSQL 16** — Banco principal (porta 5433)
- **Elasticsearch 8.15** — Engine de busca opcional
- **Redis 7** — Cache e analytics (porta 6380)

### Frontend
- **Alpine.js 3** — Framework reativo leve
- **Tailwind CSS** — Utility-first CSS

### Infraestrutura
- **Docker & Docker Compose** — Containers
- **Fly.io** — Plataforma de deploy (configurada)

---

## Comandos de Build, Teste e Desenvolvimento

### Setup Inicial

```bash
# Clone e setup
git clone git@github.com:fgamajr/gabi-kimi.git
cd gabi-kimi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configuração
cp .env.example .env
# Editar .env com credenciais

# Subir infraestrutura
python3 infra/infra_manager.py up       # PG + ES + Redis
python3 infra/infra_manager.py status   # Verificar saúde
```

### Testes

```bash
# Testes CRSS-1 (pure functions, sem DB)
python3 tests/test_commitment.py

# Testes do bulk pipeline (parsing, normalização — 135+ assertions)
python3 tests/test_bulk_pipeline.py

# Testes de ingestão DOU (211+ assertions)
python3 tests/test_dou_ingest.py

# Teste end-to-end de sealing
python3 tests/test_seal_roundtrip.py

# Parse de fixtures XML
python3 -c "from ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(f'{len(arts)} artigos parseados')"

# Compile-check de módulos
python3 -m py_compile ingest/xml_parser.py ingest/dou_ingest.py web_server.py
```

### Pipeline de Ingestão

```bash
# Download + parse últimos 7 dias (sem DB)
python3 -m ingest.bulk_pipeline --days 7 --parse-only

# Download apenas
python3 -m ingest.bulk_pipeline --days 7 --download-only

# Pipeline completo (download + parse + ingest)
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27

# Pipeline com CRSS-1 sealing
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --seal

# Ingest de ZIPs já baixados
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --skip-download
```

### Sync Incremental

```bash
# Auto-sync completo (descobre → baixa → ingere)
python3 -m ingest.sync_pipeline

# Via bulk_pipeline
python3 -m ingest.bulk_pipeline --sync

# Dry-run
python3 -m ingest.sync_pipeline --dry-run

# Refresh catálogo e sync
python3 -m ingest.sync_pipeline --refresh-catalog

# Sync range específico
python3 -m ingest.sync_pipeline --start 2025-01 --end 2026-01
```

### Schema do Banco

```bash
# Criar schemas
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/registry_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/dou_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/bm25_schema.sql

# Schema sync declarativo
python3 schema_sync.py plan --sources sources_v3.yaml
python3 schema_sync.py apply --sources sources_v3.yaml
python3 schema_sync.py verify --sources sources_v3.yaml
```

### BM25 Search

```bash
# Build completo do índice
python3 -m ingest.bm25_indexer build

# Refresh incremental
python3 -m ingest.bm25_indexer refresh

# Busca CLI
python3 -m ingest.bm25_indexer search "portaria ministério saúde"
python3 -m ingest.bm25_indexer search "licitação pregão" --date-from 2020-01-01 --section do3 -n 50

# Estatísticas
python3 -m ingest.bm25_indexer stats
```

### Elasticsearch

```bash
# Backfill completo
python3 -m ingest.es_indexer backfill --recreate-index

# Sync incremental
python3 -m ingest.es_indexer sync

# Estatísticas
python3 -m ingest.es_indexer stats
```

### Web Server

```bash
# Modo desenvolvimento
python3 web_server.py              # porta 8000
python3 web_server.py --port 3000  # porta custom

# MCP Server
python3 mcp_server.py              # stdio transport
python3 mcp_server.py --transport sse --port 8765
```

### Automação (Daily Sync)

```bash
# Sync manual completo
./scripts/daily_sync.sh

# Dry-run
./scripts/daily_sync.sh --dry-run

# Sem refresh BM25
./scripts/daily_sync.sh --no-bm25

# Via cron (diário às 6h)
crontab -e
# 0 6 * * * /caminho/para/gabi-kimi/scripts/daily_sync.sh >> /tmp/gabi_cron.log 2>&1
```

---

## Arquitetura do Banco de Dados

### Schema `dou.*` (Documentos)

| Tabela | Propósito |
|--------|-----------|
| `dou.source_zip` | Proveniência de cada ZIP baixado |
| `dou.edition` | Edições do DOU (data, seção, número) |
| `dou.document` | Documentos (atos normativos) com TSVector FTS |
| `dou.document_media` | Imagens/mídias extraídas (bytea) |
| `dou.document_signature` | Assinaturas extraídas do HTML |
| `dou.normative_reference` | Referências normativas (leis, decretos) |
| `dou.procedure_reference` | Referências processuais (SEI, etc) |

**Views Materializadas:**
- `dou.suggest_cache` — Autocomplete (órgãos, tipos, títulos)
- `dou.bm25_term_stats` — Estatísticas de termos (IDF)
- `dou.bm25_corpus_stats` — Estatísticas do corpus (N, avgdl)

### Schema `registry.*` (Audit Trail Temporal)

Tabelas append-only, imutáveis, com evidência ancorada:
- `registry.editions` — Container temporal (edition_id = SHA256)
- `registry.concepts` — Identidade de atos (natural_key_hash)
- `registry.versions` — Snapshots de conteúdo
- `registry.occurrences` — Ocorrências específicas
- `registry.ingestion_log` — Trail de auditoria com decision_basis JSONB

---

## Diretrizes de Estilo de Código

### Imports

```python
from __future__ import annotations  # Sempre primeiro

from collections import deque       # Stdlib
from dataclasses import dataclass
from typing import Any, Protocol

import yaml                         # Third-party

from ingest.xml_parser import DOUArticle  # Local imports
```

- Agrupar: stdlib, third-party, local (linha em branco entre grupos)
- Usar `from __future__ import annotations` no topo de todo módulo
- Preferir imports explícitos sobre `import *`

### Formatação

- Indentação: 4 espaços (sem tabs)
- Comprimento máximo: ~100 caracteres (flexível)
- Linhas em branco entre métodos de classe, entre funções top-level
- Sem trailing whitespace

### Type Hints

```python
def load(self, url: str) -> Page:
def extract(self, selector: str, attribute: str = "href") -> list[str]:
def _safe_load(self, runtime: RuntimeAdapter, url: str, run_id: str) -> Page | None:
```

- Usar type hints em todas as assinaturas de função
- Usar `| None` para retornos opcionais (estilo Python 3.10+)
- Usar `list[str]`, `dict[str, Any]` em vez de `List`, `Dict`

### Convenções de Nomenclatura

| Elemento | Convenção | Exemplo |
|----------|-----------|---------|
| Módulos | `snake_case` | `xml_parser.py` |
| Funções | `snake_case` | `parse_directory()` |
| Variáveis | `snake_case` | `article_count` |
| Classes | `PascalCase` | `DOUArticle` |
| Constantes | `UPPER_SNAKE_CASE` | `VALID_PUB_NAMES` |
| Privados | prefixo `_` | `_safe_load()` |
| Protocols | `PascalCase` (sem I) | `RuntimeAdapter` |
| CLI flags | `snake_case` | `--max-articles` |

### Data Classes

```python
@dataclass(slots=True)
class Page:
    url: str
    status_code: int
    html: str
    loaded_at_ms: int
```

- Usar `@dataclass(slots=True)` para containers de dados
- Usar `field(default_factory=list)` para defaults mutáveis

### Tratamento de Erros

```python
def _safe_load(self, runtime: RuntimeAdapter, url: str, run_id: str) -> Page | None:
    try:
        return runtime.load(url)
    except Exception as ex:
        self._log.error(run=run_id, stage="request", error_type=type(ex).__name__, error_message=str(ex))
        return None
```

- Logar erros com contexto estruturado via loguru
- Usar tipos específicos de exceção ao levantar
- Exceções customizadas herdam de built-ins apropriados

### Documentação

- Docstrings em nível de módulo: `"""Descrição do módulo."""`
- Docstrings em nível de classe para classes públicas
- Comentários inline com moderação; preferir código auto-documentado
- CLI help via argparse: `p.add_argument("--dates", help="Número de datas")`

---

## Estratégia de Testes

- **Sem pytest** — testes são scripts standalone executáveis
- Testes devem ser executáveis: `python3 tests/test_commitment.py`
- Para mudanças de ingestão, verificar parsing com fixtures em `tests/fixtures/xml_samples/`
- Incluir comandos de reprodução e saída esperada em descrições de PR

---

## Configuração e Segurança

### Variáveis de Ambiente (`.env`)

```bash
# PostgreSQL (obrigatório)
PG_HOST=localhost
PG_PORT=5433
PG_DB=gabi
PG_USER=gabi
PG_PASSWORD=gabi

# Search backend selector: pg (default) ou es
SEARCH_BACKEND=pg

# Elasticsearch (opcional)
ES_URL=http://localhost:9200
ES_INDEX=gabi_documents_v1
ES_ALIAS=gabi_documents

# Redis (opcional)
REDIS_URL=redis://localhost:6380/0
REDIS_PREFIX=gabi
SEARCH_ANALYTICS_ENABLED=true

# Qwen API (opcional — chat funciona sem, com fallback)
QWEN_API_KEY=sk-xxx
QWEN_MODEL=qwen-plus
```

### Segurança

- Manter secrets em `.env` (nunca commitar credenciais)
- Validar operações destrutivas no DB (`reset_db`, `recreate`)
- PostgreSQL roda na porta **5433** (não-padrão para evitar conflitos)
- `.env` está no `.gitignore`; apenas `.env.example` deve ser commitado

---

## Convenções de Commit e PR

### Commits

- Assuntos curtos, imperativos: `Fix pipeline runtime bugs`, `Add CRSS-1 commitment scheme`

### Pull Requests

Devem incluir:
- Propósito da mudança
- Paths afetados
- Comandos executados
- Comportamento antes/depois
- Link para issues relacionados
- Logs/screenshots para mudanças de workflow

---

## Armadilhas Conhecidas

1. **`data/` está no `.gitignore`** — ZIPs e catálogo não estão no git. Na máquina nova, baixe tudo via pipeline.
2. **Porta 5433** — PG Docker usa 5433 (não 5432) para evitar conflito com instâncias locais.
3. **`body_tsvector`** é populado no INSERT. Importar dump sem essa coluna quebra FTS.
4. **`suggest_cache`** e **`bm25_corpus_stats`** são materialized views — precisam `REFRESH` após novas ingestões.
5. **Smart quotes** — o web_server normaliza `""` → `""` para evitar 0 resultados.
6. **Chat organ detection** usa `suggest_cache` — se a view estiver vazia, chat não encontra órgãos.

---

## Referências Rápidas

- `README.md` — Visão geral do projeto e quickstart
- `HANDOVER.md` — Estado atual do banco e métricas
- `ARCHITECTURE_DIAGRAMS.md` — Diagramas de arquitetura
- `CODEX-ELASTIC-PLAN.MD` — Plano de migração para Elasticsearch
- `QWEN.md` — Documentação da integração Qwen
- `QUICK_REFERENCE.md` — Referência rápida de comandos
