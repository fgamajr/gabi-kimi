# GABI — Handover Document

> Gerador Automático de Boletins por Inteligência Artificial
> Data: 2026-03-04 · Branch: `feat/pythonpipe` · Commit: `f9a53a9`

---

## 1. O Que é o Projeto

Pipeline de ingestão em massa de XMLs do **DOU (Diário Oficial da União)** — baixa ZIPs mensais da Imprensa Nacional (in.gov.br), parseia XML estruturado, persiste em PostgreSQL com BM25 full-text search e serve via FastAPI + Alpine.js SPA.

## 2. Repositório

```
git clone git@github.com:fgamajr/gabi-kimi.git
cd gabi-kimi
git checkout feat/pythonpipe
```

## 3. Estado Atual do Banco (máquina antiga)

| Métrica | Valor |
|---|---|
| **Documentos** | 3,790,729 |
| **Edições** | 5,129 |
| **Período** | 2002-01-04 → 2026-01-30 |
| **ZIPs ingeridos** | 197 de 851 (amostra aleatória de 200) |
| **Tamanho do DB** | 29 GB |
| **Assinaturas** | 1,239,030 |
| **Refs normativas** | 3,487,262 |
| **Refs processuais** | 2,021,600 |
| **Mídias** | 22,082 |
| **BM25 indexed docs** | 1,053,467 (com body_word_count) |
| **Suggest cache** | 61,336 entries |

### Catálogo Completo (não ingerido)
- **851 ZIPs** em 289 meses (Jan/2002 → Jan/2026)
- Catálogo em `data/dou_catalog_registry.json` (scraped 2026-03-03)
- **654 ZIPs restantes** para ingestão completa

### Top Tipos de Ato
| Tipo | Count |
|---|---|
| extrato | 674,860 |
| aviso | 391,158 |
| portaria | 347,656 |
| pregão | 138,424 |
| edital | 86,439 |
| resultado | 74,349 |

### Top Órgãos
| Órgão | Count |
|---|---|
| Ministério da Educação | 363,107 |
| Ineditoriais | 323,223 |
| Ministério da Fazenda | 184,251 |
| Ministério da Saúde | 165,079 |
| Ministério da Defesa | 158,846 |

---

## 4. Arquitetura do Código

```
ingest/
├── bulk_pipeline.py    ← CLI orquestrador: --days/--start/--end/--sync/--seal
├── sync_pipeline.py    ← Sync incremental via catálogo
├── dou_ingest.py       ← ZIP → parse → NLP enrich → INSERT dou.*
├── html_extractor.py   ← NLP: assinaturas, imagens, refs normativas/processuais
├── multipart_merger.py ← Merge artigos multi-parte (_1, _2)
├── xml_parser.py       ← Parse XML INLabs → DOUArticle dataclass
├── zip_downloader.py   ← Download HTTP + extração ZIP
├── normalizer.py       ← DOUArticle → schema PG
├── catalog_scraper.py  ← Scrape catálogo in.gov.br (fold IDs)
├── bm25_indexer.py     ← Build/refresh BM25 index + search CLI
├── identity_analyzer.py
└── date_selector.py

dbsync/
├── dou_schema.sql      ← 7 tabelas + view + GIN FTS + btree indexes
├── bm25_schema.sql     ← Two-pass BM25 (ts_rank pre-select → BM25 re-rank)
└── schema_sync.py      ← DDL diff/apply

web_server.py           ← FastAPI: search, suggest, document, chat, media APIs
web/index.html          ← Alpine.js 3 + Tailwind CSS SPA (~895 lines)
mcp_server.py           ← MCP server com 4 tools (search, doc, stats, types)

deploy/
├── postgres/           ← Dockerfile + fly.toml + PG configs (Fly.io)
└── web/                ← Dockerfile + fly.toml + requirements.txt (Fly.io)

commitment/             ← CRSS-1 Merkle tree commitment scheme
tests/                  ← test_commitment.py, test_bulk_pipeline.py, test_dou_ingest.py
```

---

## 5. Schema PostgreSQL (`dou.*`)

```
dou.edition             ← 5,129 rows (publication_date, section, source_zipfile)
dou.document            ← 3,790,729 rows (identifica, ementa, body, art_type, issuing_organ, body_tsvector)
dou.document_signature  ← 1,239,030 rows
dou.document_media      ← 22,082 rows
dou.normative_reference ← 3,487,262 rows
dou.procedure_reference ← 2,021,600 rows
dou.source_zip          ← 197 rows

-- Materialized views
dou.bm25_term_stats     ← term frequency / document frequency
dou.bm25_corpus_stats   ← total_docs, avg_doc_length
dou.suggest_cache       ← 61,336 rows (autocomplete: órgãos, tipos, títulos)

-- Key indexes
idx_document_fts         ← GIN on body_tsvector
idx_document_art_type    ← btree
idx_document_issuing_organ ← btree
idx_document_edition     ← btree
```

---

## 6. Como Subir do Zero na Nova Máquina

### 6.1 Pré-requisitos
```bash
# Python 3.11+ (testado em 3.13)
# Docker e Docker Compose
# fly CLI (https://fly.io/docs/flyctl/install/)
```

### 6.2 Clone e Setup
```bash
git clone git@github.com:fgamajr/gabi-kimi.git
cd gabi-kimi
git checkout feat/pythonpipe

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install fastapi uvicorn[standard] httpx psycopg2-binary python-dotenv pydantic
```

### 6.3 PostgreSQL Local (Docker)
```bash
python3 infra/infra_manager.py up       # PG 16 em port 5433
python3 infra/infra_manager.py status   # Verificar saúde
```

### 6.4 Criar Schema
```bash
# Aplicar DDL do DOU
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/dou_schema.sql

# Aplicar DDL do BM25
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/bm25_schema.sql
```

### 6.5 Ingestão (do zero, sem dump)
```bash
# Opção A: Baixar + ingerir tudo (851 ZIPs, ~50 GB download, dias)
python3 -m ingest.bulk_pipeline --start 2002-01-01 --end 2026-02-01

# Opção B: Sync incremental (descobre o que falta, baixa, ingere)
python3 -m ingest.sync_pipeline --refresh-catalog

# Opção C: Ingerir só últimos N dias (teste rápido)
python3 -m ingest.bulk_pipeline --days 30

# Opção D: Parse-only (sem DB, só para validar)
python3 -m ingest.bulk_pipeline --days 7 --parse-only
```

### 6.6 BM25 Index (após ingestão)
```bash
python3 -m ingest.bm25_indexer build     # Full build (DDL + word counts + materialize)
python3 -m ingest.bm25_indexer refresh   # Incremental após novas ingestões
python3 -m ingest.bm25_indexer stats     # Verificar vocabulário e stats
```

### 6.7 Web Server
```bash
# Criar .env
cat > .env << 'EOF'
PG_HOST=localhost
PG_PORT=5433
PG_DB=gabi
PG_USER=gabi
PG_PASSWORD=gabi
# Qwen API (opcional, chat funciona sem)
# DASHSCOPE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions
# QWEN_API_KEY=sk-...
# QWEN_MODEL=qwen-plus
EOF

python3 web_server.py
# → http://localhost:8000
```

---

## 7. Funcionalidades do Web Server

### Search API (`/api/search`)
- **BM25 two-pass**: `ts_rank` pre-select top 500 → BM25 re-rank top N
- **Phrase search**: `"frase exata"`, OR, `-excluir` via `websearch_to_tsquery`
- **Browse mode**: `q=*` com filtros (btree, instant)
- **Auto-detect**: nome de órgão → redireciona para browse mode com filtro
- **Filtros**: `date_from`, `date_to`, `section`, `art_type`, `issuing_organ`

### Suggest API (`/api/suggest`)
- Autocomplete de órgãos, tipos e títulos via `suggest_cache`
- Smart: órgão → filtro instant, tipo → filtro, título → busca texto

### Chat API (`/api/chat`)
- **Linguagem natural → SQL → documentos reais**
- Detecta: órgão, tipo de ato, pessoa (FTS), limite, período
- Exemplos que funcionam:
  - "5 últimas portarias do Ministério da Saúde"
  - "editais de licitação de 2024"
  - "publicações mencionando Lula"
  - "últimos 3 decretos"
  - "resoluções da ANVISA"
- Recusa off-topic (piadas, math, receitas)
- Fallback para Qwen API se `QWEN_API_KEY` configurada

### Document API (`/api/document/{id}`)
- Documento completo com `body_html` renderizado
- Assinaturas, refs normativas, refs processuais

### Media API (`/media/{filename}`)
- Serve imagens extraídas dos XMLs

---

## 8. Performance Benchmarks (máquina antiga: i7-1365U, 7.6GB RAM)

| Query | Tempo |
|---|---|
| Órgão filter (browse mode) | **61 ms** |
| BM25 text search | **2.5 s** |
| Chat: "portarias do Min. Saúde" | **0.1 s** |
| Chat: "editais de 2024" | **1.0 s** |
| Chat: "mencionando Lula" (FTS) | **0.3 s** |
| Chat: "últimos 3 decretos" | **0.1 s** |
| Autocomplete | **< 50 ms** |

---

## 9. Fly.io Deploy (para quando for deployar)

Os configs estão prontos em `deploy/`. Na sessão anterior tentamos migrar 29GB → Fly PG via WireGuard proxy mas foi muito lento (20 MB/min = ~24h). **Decisão: re-ingerir na máquina nova.**

```bash
# Criar apps
cd deploy/postgres && fly launch --name gabi-dou-db --region gru
fly volumes create gabi_pgdata --size 100 --region gru -a gabi-dou-db
fly secrets set POSTGRES_PASSWORD=<senha> -a gabi-dou-db
fly deploy -a gabi-dou-db

cd ../web
fly launch --name gabi-dou-web --region gru
fly secrets set PG_PASSWORD=<senha> -a gabi-dou-web
fly deploy -a gabi-dou-web
```

---

## 10. O Que Falta Fazer

### Prioridade Alta
- [ ] **Ingestão completa**: 654 ZIPs restantes (851 total - 197 ingeridos)
- [ ] **BM25 refresh** após ingestão completa
- [ ] **Suggest cache refresh** (`REFRESH MATERIALIZED VIEW dou.suggest_cache`)

### Prioridade Média
- [ ] **Elasticsearch**: substituir BM25 caseiro por ES (melhor relevância, highlighting, aggregations)
- [ ] **Deploy cloud**: Fly.io ou outro provider (PG + Web + ES)
- [ ] **CRSS-1 sealing**: `--seal` no pipeline para audit trail

### Prioridade Baixa
- [ ] Qwen API key nova (a atual dá 401)
- [ ] Frontend: paginação infinita, dark mode, mobile
- [ ] Download registry schema (`dbsync/download_registry_schema.sql`)
- [ ] Ollama cleanup (`.ollama_models/` pode ser deletado — abandonamos LLM local)

---

## 11. Armadilhas Conhecidas

1. **`data/` está no .gitignore** — ZIPs e catálogo NÃO estão no git. Na máquina nova, baixe tudo via pipeline.
2. **Port 5433** — PG Docker usa 5433 (não 5432) para evitar conflito.
3. **`body_tsvector`** é populado no INSERT (trigger ou gen_tsvector column). Se importar dump sem essa coluna, FTS não funciona.
4. **`suggest_cache`** é MATERIALIZED VIEW — precisa `REFRESH` após ingestões.
5. **`bm25_corpus_stats`** idem — precisa `REFRESH` para search funcionar.
6. **Smart quotes** — o web_server normaliza `""` → `""` pra evitar 0 results.
7. **Chat organ detection** usa `suggest_cache` — se a view estiver vazia, chat não encontra órgãos.

---

## 12. Variáveis de Ambiente (.env)

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
```

---

## 13. Comandos Rápidos de Referência

```bash
# Testes (sem DB)
python3 tests/test_commitment.py
python3 tests/test_bulk_pipeline.py

# Parse fixtures
python3 -c "from ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(f'{len(arts)} articles')"

# Compile-check
python3 -m py_compile ingest/xml_parser.py ingest/dou_ingest.py web_server.py

# Infra
python3 infra/infra_manager.py up|status|down|reset_db

# BM25 Search CLI
python3 -m ingest.bm25_indexer search "portaria ministério saúde" -n 10

# Catalog
python3 -m ingest.catalog_scraper --start-year 2002 --end-year 2026
```
