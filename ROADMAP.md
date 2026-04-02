# GABI — RAG Rebuild Roadmap
**Last updated:** 2026-04-02  
**Status:** Sprint 0 in progress (embedding PoC completed)

---

## Project Context

GABI is a full-text search platform for Brazil's Diário Oficial da União (~16M DOU documents, 2002–2026) and TCU jurisprudence (~520K acórdãos, 1992–2026). Stack: Python 3.12, FastAPI, MongoDB 7, Elasticsearch 8.15.4, Hetzner CPX42 (8 vCPU / 16GB RAM), domain gabidou.top.

The current system has two incompatible embedding pipelines (DOU: 384-dim Qwen3 MLX/Apple Silicon only; TCU: 1536-dim OpenAI→ES). This rebuild replaces both with a unified architecture: **Postgres as raw archive + source-dependent parsers + pgvector embeddings + ES BM25**.

---

## Core Architectural Decisions (already made)

### ADR-001: Embedding model
- **Gemini `gemini-embedding-2-preview`** selected over Qwen3-Embedding-0.6B (local)
- Gemini PoC results: recall@10 avg=0.12 (note: BM25 ground truth over 16M index vs 1K sample — absolute low but comparable); dims=3072; latency p50=464ms; cost est. $29.25/1M docs
- Qwen3 PoC blocked by batch-size issue (1000 texts → server disconnect). Batching fix needed for fair comparison. Service `gabi-kimi-qwen-embed` deployed (custom `ops/qwen_embed_server.py`, sentence-transformers, port 8900, profile=embedding).
- **Decision: Gemini API for production. Qwen3 local as fallback/cost hedge.**

### ADR-002: Storage architecture
- **Postgres** as Source of Truth (replaces MongoDB entirely)
- **pgvector** for dense embeddings (replaces ES dense_vector)
- **Elasticsearch** retained for BM25 lexical search only (new index `gabi_documents_v4`)
- MongoDB destroyed after validated ETL — NOT before

### ADR-003: Parsing strategy (KEY DECISION — discuss before Sprint 2)
- **Raw archive first, parse later** — ETL copies MongoDB fields verbatim to Postgres with integrity hash. No transformation during ETL.
- **Source-dependent parsers** — one parser class per document type cluster. Different structure, different XML-like tags.
- **LLM enrichment** — async `<RESUMO>` generation for eligible documents, stored as separate chunk

---

## What We Know About the Raw Data

### DOU `documents` collection (80 fields, ~16M docs)
Critical fields:
- `content_html`: str(~9KB avg) — **raw HTML from INLABS XML — the re-parsing source**
- `content_hash`: str(64) — SHA256 of **processed text** (NOT of content_html — do NOT use as integrity hash)
- `art_type_normalized`: str — document type classifier
- `natural_key_hash`, `occurrence_hash`, `edition_id` — deduplication keys
- `parse_quality_score`: float — proxy for LLM enrichment tiering
- `signatures`, `normative_references`, `procedure_references`: already extracted lists
- `source_zip`: str — which ZIP file it came from

**Important:** `content_html` IS stored in Mongo. No need to re-download from INLABS to re-parse.

### TCU `tcu_acordaos` collection (68 fields, ~520K docs)
Critical fields:
- `tipo`: "ACÓRDÃO" (completo) or "ACÓRDÃO DE RELAÇÃO" (por relação)
- `has_relatorio`: bool — true only in completo
- `has_voto`: bool — true only in completo
- `completeness_score`: float (completo ~0.67, relação ~0.17)
- `relatorio`: str (up to ~48K chars) — null in por relação
- `voto`: str (~7.7K chars) — null in por relação
- `acordao_texto`: str (~1.1K) — always present (the dispositivo)
- `sumario`: str — executive summary (null in por relação)
- `assunto`, `quorum`, `interessados`, `declaracao_voto`, `voto_complementar`: str
- `deterministic_hash`: str(64) — natural key hash (not content hash)
- `source_csv`: "acordao-completo-YYYY.csv"
- **NO `content_html`** — TCU came from CSV. `acordao_texto` IS the raw. Better TCU quality requires original CSVs.

### Other TCU collections — FIELDS NOT YET INSPECTED
`tcu_normas`, `tcu_publicacoes`, `tcu_btcu` — must inspect before Sprint 2 parser design.
```bash
ssh gabi-prod 'docker exec gabi-kimi-backend python3 -c "
from pymongo import MongoClient; import os
db = MongoClient(os.environ[\"MONGO_STRING\"])[\"gabi_dou\"]
for c in [\"tcu_normas\", \"tcu_publicacoes\", \"tcu_btcu\"]:
    doc = db[c].find_one({})
    print(c, list(doc.keys()) if doc else \"empty\")
"'
```

### DOU Document Type Clusters (from ES aggregation on ~16M docs)
| Cluster | art_type_normalized values | ~Volume |
|---|---|---|
| Extrato contratual | extrato, extrato de contrato, extrato de termo aditivo, extrato de convênio, extrato de RP, extrato de inexigibilidade, extrato de dispensa, extrato de apostilamento, extrato de doação | ~4.7M |
| Portaria/Normativo | portaria, resolução, ato, despacho, decisão, comunicado | ~3.9M |
| Licitação | aviso de licitação (todas modalidades), pregão, edital, concorrência, tomada | ~2.3M |
| Resultado | resultado, resultado de julgamento, aviso de homologação, aviso de homologação e adjudicação | ~0.7M |
| Retificação/Aviso | retificação, retificações, aviso, aviso de retificação, aviso de suspensão, aviso de alteração | ~0.5M |
| Outros | alvará, ata, extrato da ata, edital de notificação... | ~0.3M |

---

## Sprint Plan

### Sprint 0 — Decisions + Unblock ✅ IN PROGRESS
- [x] Embedding PoC: Gemini `gemini-embedding-2-preview` tested (500 DOU + 500 TCU, 3 runs). Artifact: `ops/baselines/embedding_poc_20260402_full_comparison.json`
- [x] Linux embedder: `gabi-kimi-qwen-embed` container deployed (sentence-transformers, port 8900, profile=embedding). Healthy.
- [x] Baseline search metrics: `ops/baselines/baseline_20260402_04f6babe.json`
- [x] `ops/qwen_embed_server.py`: custom FastAPI server, OpenAI-compat `/v1/embeddings`
- [ ] ADR-001 formally signed
- [ ] Qwen3 batching fix (optional — batch in 32-text chunks in `qwen_embed_server.py`)

---

### Sprint 1 — Raw Archive (MongoDB → Postgres, no transformation)
**Goal:** Faithful copy of all MongoDB collections into Postgres with real integrity hashes. Destroy MongoDB after validation.

**Step 0:** Add Postgres service to `docker-compose.prod.yml`:
```yaml
  postgres:
    image: pgvector/pgvector:pg16
    container_name: gabi-kimi-postgres
    restart: unless-stopped
    env_file: .env
    environment:
      POSTGRES_DB: gabi
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ${GABI_HOST_DATA_ROOT}/postgres_data:/var/lib/postgresql/data
    expose:
      - "5432"
    networks:
      - internal
```

**DDL — schema `raw`:**
```sql
CREATE SCHEMA raw;

-- DOU: all 80 fields preserved verbatim in JSONB + structural columns for indexing
CREATE TABLE raw.dou_documents (
    id              TEXT PRIMARY KEY,       -- MongoDB _id
    pub_date        DATE NOT NULL,
    section         TEXT,
    source_zip      TEXT,
    art_type        TEXT,
    content_html    TEXT,                   -- raw HTML for re-parsing
    raw_html_hash   TEXT NOT NULL,          -- SHA256(content_html) — integrity hash
    all_fields      JSONB NOT NULL,         -- all 80 fields verbatim
    migrated_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON raw.dou_documents (pub_date);
CREATE INDEX ON raw.dou_documents (art_type);
CREATE INDEX ON raw.dou_documents (raw_html_hash);

-- TCU acórdãos: all 68 fields
CREATE TABLE raw.tcu_acordaos (
    id              TEXT PRIMARY KEY,       -- MongoDB _id
    tipo            TEXT,                   -- "ACÓRDÃO" or "ACÓRDÃO DE RELAÇÃO"
    has_relatorio   BOOLEAN,
    has_voto        BOOLEAN,
    data_sessao     DATE,
    colegiado       TEXT,
    raw_text_hash   TEXT NOT NULL,          -- SHA256(acordao_texto)
    all_fields      JSONB NOT NULL,
    migrated_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON raw.tcu_acordaos (tipo);
CREATE INDEX ON raw.tcu_acordaos (data_sessao);

-- Migration audit log
CREATE TABLE raw.migration_log (
    id              SERIAL PRIMARY KEY,
    collection      TEXT NOT NULL,
    count_mongo     BIGINT,
    count_postgres  BIGINT,
    hash_errors     INT DEFAULT 0,
    duration_s      FLOAT,
    ran_at          TIMESTAMPTZ DEFAULT now()
);

-- Repeat pattern for tcu_normas, tcu_publicacoes, tcu_btcu after field inspection
```

**ETL script `ops/etl_mongo_to_postgres.py`:**
- Cursor-based, batch 1000, idempotent (`ON CONFLICT DO NOTHING`)
- Compute `SHA256(content_html)` for DOU (NOT the existing `content_hash` — it's wrong)
- Compute `SHA256(acordao_texto)` for TCU
- Write migration_log entry per collection run
- Validate: COUNT parity + spot-check 1000 random hashes

**MongoDB destruction gate:**
1. COUNT(*) parity: 100% per collection
2. Hash spot-check: 0 divergences in 1000 random docs
3. `sync_dou.py` stopped (no new writes)
4. Mongo → read-only → shutdown → volume archived (keep 30 days)

---

### Sprint 2 — Source-Dependent Parsers
**Goal:** Parse raw Postgres content into structured, LLM-readable tagged documents.

**Prerequisite:** Inspect `tcu_normas`, `tcu_publicacoes`, `tcu_btcu` fields first.

**Parser interface:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class Chunk:
    text: str
    chunk_type: str      # "ementa", "relatorio", "voto", "acordao", "body", "artigos"
    section_tag: str     # "<EMENTA>", "<VOTO>", etc.
    char_start: int
    char_end: int
    order: int

@dataclass
class ParsedDocument:
    source_id: str
    parser_name: str
    parser_version: str  # semver "1.0.0"
    body_clean: str      # full tagged text
    chunks: list[Chunk]
    section_structure: dict
    metadata: dict

class RawParser(Protocol):
    source: str
    version: str
    def parse(self, raw_fields: dict) -> ParsedDocument: ...
```

**TCU parsers:**

`TcuAcordaoCompletoParser` (when `tipo == "ACÓRDÃO"` and `has_relatorio == True`):
```
<EMENTA>{sumario}</EMENTA>
<ASSUNTO>{assunto}</ASSUNTO>
<RELATORIO>{relatorio}</RELATORIO>
<VOTO>{voto}</VOTO>
<ACORDAO>{acordao_texto}</ACORDAO>
<QUORUM>{quorum}</QUORUM>
```
Each section = one chunk. Long sections (relatorio) split at paragraph boundaries into ~600-token sub-chunks preserving tag context.

`TcuAcordaoRelacaoParser` (when `tipo == "ACÓRDÃO DE RELAÇÃO"`):
```
<EMENTA>{sumario or assunto}</EMENTA>
<ACORDAO>{acordao_texto}</ACORDAO>
```

**DOU parsers by cluster** (dispatch on `art_type_normalized`):

`DouExtratoParser` (extrato*, convênio, cooperação):
```
<PARTES>{contratante} / {contratada}</PARTES>
<OBJETO>{objeto}</OBJETO>
<VALOR>{valor}</VALOR>
<VIGENCIA>{vigencia}</VIGENCIA>
<FUNDAMENTO>{fundamento_legal}</FUNDAMENTO>
```

`DouNormativoParser` (portaria, resolução, ato, despacho, decisão):
```
<EMENTA>{ementa}</EMENTA>
<CONSIDERANDOS>{considerandos}</CONSIDERANDOS>
<ARTIGOS>{art1}\n{art2}\n...</ARTIGOS>
```

`DouLicitacaoParser` (aviso*, pregão, edital, concorrência, tomada):
```
<OBJETO>{objeto}</OBJETO>
<MODALIDADE>{modalidade}</MODALIDADE>
<ORGAO>{orgao}</ORGAO>
<DATAS>{abertura} / {encerramento}</DATAS>
<CONDICOES>{corpo}</CONDICOES>
```

`DouResultadoParser` (resultado*, homologação*):
```
<REFERENCIA>{licitacao_referenciada}</REFERENCIA>
<VENCEDOR>{vencedor}</VENCEDOR>
<VALOR>{valor}</VALOR>
```

`DouGenericoParser` (fallback — aviso, comunicado, retificação, outros):
```
<EMENTA>{identifica}</EMENTA>
<CORPO>{clean_body}</CORPO>
```

**Output DDL:**
```sql
CREATE SCHEMA parsed;

CREATE TABLE parsed.dou_documents (
    id               TEXT PRIMARY KEY REFERENCES raw.dou_documents(id),
    parser_name      TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    body_clean       TEXT NOT NULL,
    chunks           JSONB NOT NULL,
    section_structure JSONB,
    parsed_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE parsed.tcu_acordaos (
    id               TEXT PRIMARY KEY REFERENCES raw.tcu_acordaos(id),
    parser_name      TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    body_clean       TEXT NOT NULL,
    chunks           JSONB NOT NULL,
    section_structure JSONB,
    parsed_at        TIMESTAMPTZ DEFAULT now()
);
```

**Parser versioning:** bump `parser_version` on improvement. Re-run only: `WHERE parser_version != 'current_version'`.

**Validation before full run:** run parsers on 1000-doc sample. Human review of tagged output. Check: all sections extracted, no empty chunks, tag balance.

---

### Sprint 3 — LLM Enrichment (async, background, runs in parallel with Sprint 4)
**Goal:** `<RESUMO>` chunks generated by LLM for eligible documents.

**Eligibility tiering:**
| Tier | Documents | Generate RESUMO |
|---|---|---|
| High | TCU acórdãos completos, portarias, normas, editais | Always |
| Medium | Extratos longos (>500 chars), avisos complexos | Optional |
| Low | Atos de pessoal curtos, retificações simples | Never |

**Output DDL:**
```sql
CREATE SCHEMA enriched;

CREATE TABLE enriched.llm_summaries (
    doc_id            TEXT NOT NULL,
    corpus            TEXT NOT NULL,      -- "dou" or "tcu"
    llm_model         TEXT NOT NULL,
    llm_model_version TEXT NOT NULL,
    resumo            TEXT NOT NULL,
    generated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (doc_id, llm_model_version)
);
```

Stored as chunk_type="resumo_llm" in the embedding pipeline. Can be regenerated independently as LLM quality improves.

**Open decision:** Gemini Flash (cheap API) vs local Qwen (free, slow) for RESUMO generation.

---

### Sprint 4 — Embeddings + pgvector + ES v4

**Embedder (`ops/embed_indexer_v2.py`):**
- Reads `parsed.*.chunks` + `enriched.llm_summaries` from Postgres
- Calls Gemini `gemini-embedding-2-preview` (dims=3072), batch 100 texts, retry on 429/5xx
- Writes to `embeddings.chunks`

```sql
CREATE SCHEMA embeddings;

CREATE TABLE embeddings.chunks (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    corpus          TEXT NOT NULL,
    chunk_order     INT NOT NULL,
    chunk_type      TEXT NOT NULL,
    text            TEXT NOT NULL,
    embedding       vector(3072),
    model_version   TEXT NOT NULL,
    embedded_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON embeddings.chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200);
```

**ES indexer v4:** reads `parsed.*` → `gabi_documents_v4` (lexical-only, no dense_vector). Alias swap `gabi_documents` → v4.

**Query Tool v2:** `RRF(ES BM25, pgvector kNN)`. Feature flag `QUERY_V2_ENABLED`. Shadow mode (log both v1+v2, compare offline).

---

### Sprint 5 — Cutover + Cleanup
- Gate: shadow discordance < threshold (define before cutover)
- Flip `QUERY_V2_ENABLED=true`
- Rollback: flip back, keep v1 frozen 2 weeks
- Delete: embed_indexer.py (ES-targeting), MLX server, ES chunks v1, ES indexes v1/v2/v3
- MongoDB volume: archive, delete after 30 days

---

## Files & Services Reference

### Key files
| File | Purpose |
|---|---|
| `ROADMAP.md` | This document — single source of truth |
| `AGENTS.md` | Architecture overview, build commands |
| `CLAUDE.md` | Claude Code instructions |
| `ops/embedding_poc.py` | Embedding benchmark |
| `ops/qwen_embed_server.py` | Custom embedding server (sentence-transformers) |
| `ops/baselines/` | Versioned benchmark artifacts |
| `src/backend/ingest/dou_processor.py` | Current DOU parser (replaced in Sprint 2) |
| `src/backend/ingest/sync_dou.py` | INLABS ingestion pipeline |
| `docker-compose.prod.yml` | Production services |
| `Dockerfile.qwen-embed` | Qwen embedding service image |

### Deployed services (Hetzner CPX42, IP: 204.168.173.163)
| Service | Port | Status |
|---|---|---|
| backend (FastAPI) | 8001 | healthy |
| elasticsearch | 9200 (internal) | healthy |
| mongodb | 27017 (internal) | healthy |
| qwen-embed | 8900 (internal, profile=embedding) | healthy |
| frontend | 8081 | healthy |
| Caddy (TLS) | 443 | healthy → gabidou.top |

### Relevant env vars
```bash
EMBED_SERVER_URL=http://qwen-embed:8900
EMBED_DIMS=384
GEMINI_API_KEY=...
GEMINI_API_MODELS=gemini-embedding-2-preview
GEMINI_EMBED_PRICE_PER_1K_TOKENS=0.0001
# To add in Sprint 1:
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DSN=postgresql://user:pass@postgres:5432/gabi
```

---

## Open Questions / Decisions Pending

1. **ADR-001 sign-off:** Gemini confirmed? Or fix Qwen3 batching first for fair cost comparison?
2. **TCU other collections:** inspect `tcu_normas`, `tcu_publicacoes`, `tcu_btcu` fields before Sprint 2
3. **Chunking size:** current limit is 2000 chars. Gemini accepts up to 2048 tokens. Optimal ~600 tokens. Revisit in Sprint 2.
4. **LLM for RESUMO:** Gemini Flash vs local Qwen. Affects Sprint 3.
5. **Parser validation sample:** define acceptance criteria before full Sprint 2 run.
6. **Qwen3 batching fix:** `ops/qwen_embed_server.py` needs internal batching (chunks of 32) before another PoC run.

---

## How to Resume in a New Session

1. Read this file (`ROADMAP.md`) first — complete plan is here.
2. Check memory files at `~/.claude/projects/-Users-fgamajr-dev-gabi-kimi/memory/` for additional context (user profile, prod deployment notes, MCP config, etc).
3. Current state: Sprint 0, all changes committed on `main`, pushed to GitHub.
4. **Next action: Sprint 1** — add Postgres+pgvector to `docker-compose.prod.yml`, write DDL, write `ops/etl_mongo_to_postgres.py`.

**Trigger phrase for next session:** "Vamos começar o Sprint 1 do ROADMAP — DDL do schema raw no Postgres e script de ETL."
