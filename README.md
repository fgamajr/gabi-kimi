# GABI — Gerador Automático de Boletins por Inteligência Artificial

Pipeline de ingestão em massa do **Diário Oficial da União (DOU)** — baixa ZIPs mensais da Imprensa Nacional (in.gov.br), parseia XML estruturado, persiste em PostgreSQL com full-text search BM25 e serve via FastAPI + Alpine.js SPA.

## Visão Geral

| Dado | Valor |
|---|---|
| **Cobertura** | Jan/2002 → presente |
| **Catálogo completo** | 851 ZIPs em 289 meses |
| **Schema** | 7 tabelas + views materializadas + GIN FTS |
| **Stack** | Python 3.13, PostgreSQL 16, FastAPI, Alpine.js 3, Tailwind CSS |
| **Busca** | BM25 two-pass (ts_rank → BM25 re-rank) |
| **Auditoria** | CRSS-1 Merkle tree commitment scheme |

---

## Quickstart

### Pré-requisitos

- Python 3.11+
- Docker e Docker Compose

### Setup

```bash
git clone git@github.com:fgamajr/gabi-kimi.git
cd gabi-kimi
git checkout feat/pythonpipe

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install fastapi uvicorn[standard] httpx psycopg2-binary python-dotenv pydantic
```

### Subir o banco

```bash
python3 infra/infra_manager.py up       # PostgreSQL 16 (:5433) + Elasticsearch (:9200) + Redis (:6380)
python3 infra/infra_manager.py status   # Verificar saúde dos serviços
```

### Criar schema

```bash
# Pipeline temporal append-only (registry.*), usado por bulk/sync
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/registry_schema.sql

# Schema DOU relacional (dou.*), usado por ingest.dou_ingest
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/dou_schema.sql

# BM25 sobre dou.*
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/bm25_schema.sql
```

### Ingestão

```bash
# Sync completo (descobre novos ZIPs, baixa, ingere em registry.*)
python3 -m ingest.sync_pipeline --refresh-catalog

# Ou: últimos N dias (registry.*)
python3 -m ingest.bulk_pipeline --days 30

# Ou: período específico (registry.*)
python3 -m ingest.bulk_pipeline --start 2024-01-01 --end 2024-12-31

# Ou: parse-only (sem DB, só validação)
python3 -m ingest.bulk_pipeline --days 7 --parse-only

# Para preencher dou.* a partir de ZIPs já baixados:
python3 -m ingest.dou_ingest --data-dir data/inlabs
```

### BM25 e Autocomplete

```bash
# Build completo do índice BM25 (após ingestão)
python3 -m ingest.bm25_indexer build

# Refresh incremental (após novas ingestões)
python3 -m ingest.bm25_indexer refresh

# Refresh suggest cache (autocomplete)
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi \
  -c "REFRESH MATERIALIZED VIEW CONCURRENTLY dou.suggest_cache;"
```

### Elasticsearch (backfill + sync)

```bash
# Criar índice + backfill completo (a partir de dou.document)
python3 -m ingest.es_indexer backfill --recreate-index

# Sync incremental (somente documentos novos)
python3 -m ingest.es_indexer sync

# Estatísticas/paridade PG x ES
python3 -m ingest.es_indexer stats
```

### Web Server

```bash
# Configurar variáveis
cp .env.example .env
# Editar .env com suas credenciais (ver seção Configuração)

python3 web_server.py
# → http://localhost:8000
```

---

## Arquitetura

```
ingest/
├── bulk_pipeline.py     ← CLI orquestrador: --days/--start/--end/--sync/--seal
├── sync_pipeline.py     ← Sync incremental via catálogo
├── dou_ingest.py        ← ZIP → parse → NLP enrich → INSERT dou.*
├── html_extractor.py    ← NLP: assinaturas, imagens, refs normativas/processuais
├── multipart_merger.py  ← Merge artigos multi-parte (_1, _2)
├── xml_parser.py        ← Parse XML INLabs → DOUArticle dataclass
├── zip_downloader.py    ← Download HTTP + extração ZIP
├── normalizer.py        ← DOUArticle → schema PG
├── catalog_scraper.py   ← Scrape catálogo in.gov.br (folderId por mês)
├── bm25_indexer.py      ← Build/refresh BM25 index + search CLI
├── identity_analyzer.py ← Identity hashing e deduplicação
└── date_selector.py     ← Geração de ranges de datas

dbsync/
├── dou_schema.sql       ← 7 tabelas + view + GIN FTS + btree indexes
├── bm25_schema.sql      ← Two-pass BM25 (ts_rank pre-select → BM25 re-rank)
└── schema_sync.py       ← DDL diff/apply

web_server.py            ← FastAPI: search, suggest, document, chat, media APIs
web/index.html           ← Alpine.js 3 + Tailwind CSS SPA
mcp_server.py            ← MCP server com 4 tools (search, doc, stats, types)

commitment/              ← CRSS-1 Merkle tree commitment scheme
scripts/daily_sync.sh    ← Sync diário automatizado (cron/systemd)
infra/                   ← Docker-based PostgreSQL appliance
tests/                   ← Suíte de testes (346+ assertions)
```

### Schema PostgreSQL (`dou.*`)

```
dou.edition             ← Edições (publication_date, section, source_zipfile)
dou.document            ← Documentos (identifica, ementa, body, art_type, issuing_organ, body_tsvector)
dou.document_signature  ← Assinaturas
dou.document_media      ← Imagens/mídias extraídas dos XMLs
dou.normative_reference ← Refs a normas (leis, decretos, portarias)
dou.procedure_reference ← Refs a processos (números processuais)
dou.source_zip          ← Registry de ZIPs ingeridos (dedup)

-- Views materializadas
dou.bm25_term_stats     ← Frequência de termos (TF/DF)
dou.bm25_corpus_stats   ← Total docs, avg doc length
dou.suggest_cache       ← Autocomplete (órgãos, tipos, títulos)

-- Indexes principais
idx_document_fts         ← GIN on body_tsvector
idx_document_art_type    ← btree
idx_document_issuing_organ ← btree
idx_document_edition     ← btree
```

---

## Funcionalidades do Web Server

### Busca (`/api/search`)
- **BM25 two-pass**: `ts_rank` pré-seleciona top 500 → BM25 re-ranqueia top N
- **Phrase search**: `"frase exata"`, OR, `-excluir` via `websearch_to_tsquery`
- **Browse mode**: `q=*` com filtros (btree, instant)
- **Auto-detect**: nome de órgão → redireciona para browse com filtro
- **Filtros**: `date_from`, `date_to`, `section`, `art_type`, `issuing_organ`

### Autocomplete (`/api/suggest`)
- Sugestões de órgãos, tipos de ato e títulos via `suggest_cache`
- órgão → filtro instantâneo, tipo → filtro, título → busca texto

### Chat (`/api/chat`)
- **Linguagem natural → SQL → documentos reais**
- Detecta: órgão, tipo de ato, pessoa (FTS), limite, período
- Exemplos:
  - "5 últimas portarias do Ministério da Saúde"
  - "editais de licitação de 2024"
  - "publicações mencionando Lula"
  - "resoluções da ANVISA"
- Fallback para Qwen API se `QWEN_API_KEY` configurada

### Documento (`/api/document/{id}`)
- Documento completo com body HTML renderizado, assinaturas, refs

### Mídia (`/media/{filename}`)
- Serve imagens extraídas dos XMLs do DOU

---

## Sync Automático

O script `scripts/daily_sync.sh` automatiza o ciclo completo:

1. Verifica saúde do PostgreSQL
2. Atualiza o catálogo de ZIPs (`catalog_scraper`)
3. Descobre e baixa ZIPs novos (`sync_pipeline`)
4. Ingere no banco
5. Atualiza índice BM25 e suggest cache

### Uso manual

```bash
./scripts/daily_sync.sh              # Sync completo
./scripts/daily_sync.sh --dry-run    # Mostra o que seria feito
./scripts/daily_sync.sh --no-bm25    # Pula refresh do BM25
```

### Via cron (diário às 6h)

```bash
crontab -e
# Adicionar:
0 6 * * * /caminho/para/gabi-kimi/scripts/daily_sync.sh >> /tmp/gabi_cron.log 2>&1
```

### Via systemd timer

```bash
# Copiar units (substituir SEU_USUARIO)
sudo cp scripts/gabi-sync@.service /etc/systemd/system/
sudo cp scripts/gabi-sync@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gabi-sync@SEU_USUARIO.timer
```

Logs ficam em `data/logs/sync_YYYY-MM-DD.log`.

---

## CLI de Busca BM25

```bash
# Busca livre
python3 -m ingest.bm25_indexer search "portaria ministério saúde"

# Com filtros
python3 -m ingest.bm25_indexer search "licitação pregão" \
  --date-from 2020-01-01 --section do3 -n 50

# Estatísticas do índice
python3 -m ingest.bm25_indexer stats
```

## Plano Elasticsearch

Migração planejada e faseada para Elasticsearch (com rollback para PG BM25):

- Ver plano: `CODEX-ELASTIC-PLAN.MD`
- Estratégia: PostgreSQL continua como fonte canônica; Elasticsearch vira engine de busca
- Rollback: `SEARCH_BACKEND=pg`

---

## Testes

```bash
# CRSS-1 commitment scheme (pure functions, sem DB)
python3 tests/test_commitment.py

# Bulk pipeline (parsing, normalização, extração — 135+ assertions)
python3 tests/test_bulk_pipeline.py

# DOU ingest (211+ assertions)
python3 tests/test_dou_ingest.py

# Parse fixtures XML
python3 -c "from ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(f'{len(arts)} articles parsed')"

# Compile-check
python3 -m py_compile ingest/xml_parser.py ingest/dou_ingest.py web_server.py
```

---

## Configuração (`.env`)

```bash
# PostgreSQL (obrigatório)
PG_HOST=localhost
PG_PORT=5433
PG_DB=gabi
PG_USER=gabi
PG_PASSWORD=gabi

# Qwen API (opcional — chat funciona sem, com fallback inteligente)
DASHSCOPE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_API_KEY=sk-xxx
QWEN_MODEL=qwen-plus

# Search backend (migração para Elasticsearch)
SEARCH_BACKEND=pg
ES_URL=http://localhost:9200
ES_INDEX=gabi_documents_v1
ES_ALIAS=gabi_documents
ES_USERNAME=
ES_PASSWORD=
ES_VERIFY_TLS=false

# Redis (autocomplete cache + top searches)
REDIS_URL=redis://localhost:6380/0
REDIS_PREFIX=gabi
SEARCH_ANALYTICS_ENABLED=true
TOP_SEARCH_MIN_QUERY_LEN=3
TOP_SEARCH_MAX_QUERY_LEN=120
SUGGEST_CACHE_TTL_SEC=120
```

---

## Infraestrutura

```bash
python3 infra/infra_manager.py up        # Subir PostgreSQL + Elasticsearch + Redis
python3 infra/infra_manager.py status    # Verificar container e DB
python3 infra/infra_manager.py down      # Parar
python3 infra/infra_manager.py reset_db  # Wipe DB (destrutivo!)
```

O PostgreSQL roda na porta **5433** (não 5432) para evitar conflito com instâncias locais.

---

## Catálogo DOU

```bash
# Scrape completo (Jan/2002 → presente)
python3 -m ingest.catalog_scraper --start-year 2002 --end-year 2026

# Registry salvo em data/dou_catalog_registry.json
```

O catálogo mapeia meses para `folderId`s da API in.gov.br. Atualmente: 289 meses, 851 ZIPs.

---

## Backup e Portabilidade

Após ingestão, um `pg_dump` captura todo o estado:

```bash
pg_dump -h localhost -p 5433 -U gabi -d gabi -Fc -f gabi_full.dump
```

Para restaurar em outra máquina:

```bash
pg_restore -h localhost -p 5433 -U gabi -d gabi -Fc gabi_full.dump
```

O dump inclui schema, dados, indexes, views materializadas e funções BM25. Os ZIPs não são necessários após ingestão.

---

## Armadilhas Conhecidas

1. **`data/` está no `.gitignore`** — ZIPs e catálogo não estão no git. Na máquina nova, baixe tudo via pipeline.
2. **Porta 5433** — PG Docker usa 5433 (não 5432) para evitar conflito.
3. **`body_tsvector`** é populado no INSERT. Importar dump sem essa coluna quebra FTS.
4. **`suggest_cache`** e **`bm25_corpus_stats`** são materialized views — precisam `REFRESH` após novas ingestões.
5. **Smart quotes** — o web_server normaliza `""` → `""` para evitar 0 resultados.
6. **Chat organ detection** usa `suggest_cache` — se a view estiver vazia, chat não encontra órgãos.

---

## Roadmap

- [ ] **Elasticsearch** — executar `CODEX-ELASTIC-PLAN.MD` (fases 1-6)
- [ ] **Deploy cloud** — Fly.io ou outro provider (PG + Web + ES)
- [ ] **CRSS-1 sealing** — `--seal` no pipeline para audit trail criptográfico
- [ ] **Frontend** — paginação infinita, dark mode, mobile responsive

---

## Licença

Projeto interno. Dados do DOU são públicos conforme legislação brasileira.
