# GABI DOU — Busca Inteligente no Diário Oficial da União

**[gabidou.top](https://gabidou.top)** — Full-text search over ~16M Brazilian government gazette documents (2002–2026), with intent-based ranking, PDF generation, and dynamic trending.

## Live System

- **15.8M+ documents** indexed from the Diário Oficial da União
- **520K+ TCU acórdãos** (1992–2026) with semantic search and facets by colegiado/relator
- **TCU Publicações Institucionais**: relatórios de auditoria, sumários executivos, cartilhas, manuais — scraped from portal.tcu.gov.br
- **Intent-based search**: queries automatically classified as exact name, canonical law, person name, trending, or thematic exploration
- **PDF generation**: DOU-style A4 PDFs with coat of arms, two-column layout, serif typography
- **Light/dark mode** with system preference detection

## Architecture

```
INLABS (in.gov.br)
    ↓  inlabs_daily.py (server cron via residential proxy)
MongoDB 7 (16M documents)
    ↓  es_indexer.py (cursor-based sync)
Elasticsearch 8.15 (BM25 + function_score ranking)
    ↑
FastAPI backend ──→ React frontend (Vite production build)
    ↑
nginx (HTTPS, Let's Encrypt) → gabidou.top
```

### Production topology (Hetzner CPX42)

| Service | Port | Role |
|---------|------|------|
| nginx (host) | 80/443 | HTTPS termination, reverse proxy |
| frontend | 8081→8080 | Vite production build (preview mode) |
| backend | 8001→8000 | FastAPI API |
| worker | — | Background ES sync |
| mongo | 27017 | Document storage (authenticated) |
| elasticsearch | 9200 | Full-text search index |

## Stack

| Layer | Tech |
|-------|------|
| Ingestion | Python, pymongo, lxml, requests |
| Database | MongoDB 7 (Docker) |
| Search | Elasticsearch 8.15.4 (Docker) |
| Backend | FastAPI, uvicorn, httpx |
| Frontend | Vite 5 + React 18 + Tailwind CSS + shadcn/ui + TypeScript |
| PDF | weasyprint (HTML→PDF with CSS @page rules) |
| Theme | next-themes (light default, dark toggle) |

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:8081
- Backend API: http://localhost:8001
- API Health: http://localhost:8001/api/health

## Search Features

### Intent-Based Query Classification

The search pipeline automatically classifies queries into 5 intents, each with its own ranking strategy:

| Intent | Example | Ranking Strategy |
|--------|---------|------------------|
| **EXACT_NAME** | "Lei 13709", "Portaria MEC 234" | Structured field lookup (art_type + document_number), no recency decay |
| **CANONICAL** | "LGPD", "Código Penal", "CLT" | Popular name → formal reference pin + regulatory cluster boost |
| **PERSON** | "Fernando Lima Gama Júnior" | Phrase match with orthographic variants (Y↔I, PH↔F), no recency decay |
| **TRENDING** | "concursos", "nomeação", "licitação" | Heavy recency (gauss 30d scale), art_type boost from topic metadata |
| **SUBJECT** | "dispensa licitação emergência saúde" | Phrase proximity (slop=3) + soft recency (180d) + canonical art_type boost |

Classification priority: EXACT_NAME → CANONICAL → PERSON → TRENDING → SUBJECT

### Fuzzy Normalization (EXACT_NAME)

The normalizer handles imperfect input:
- `"port. MEC 234/26"` → Portaria MEC 234/2026
- `"IN RFB 2005"` → Instrução Normativa RFB 2005
- `"dec. 9064/2017"` → Decreto 9064/2017
- `"LC 101"` → Lei Complementar 101

### Canonical Laws Dictionary

30+ Brazilian laws mapped by popular name (`src/backend/data/canonical_laws.json`):
- "LGPD" → Lei 13.709/2018 + boost ANPD docs
- "CLT" → Decreto-Lei 5.452/1943
- "Lei Maria da Penha" → Lei 11.340/2006
- "Lei de Licitações" → Lei 14.133/2021 + Lei 8.666/1993

### Homepage Cache Refresh

`GET /api/trending` returns curated topics with publication counts, and `GET /api/editorial-highlights` serves the homepage editorial board from cache.

The homepage cache is refreshed in two ways:
- as part of the daily ingest pipeline after sync/embedding completes
- by a backup cron around `09:00 America/Sao_Paulo` via `ops/bin/update_homepage_cache.sh`

Homepage sections that depend on this refresh:
- trending chips ("Em alta no DOU")
- editorial highlights / news board

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/search?q=...` | Full-text search with intent classification |
| `GET /api/search?q=...&intent=trending&is_trending=true` | Force trending ranking |
| `GET /api/document/{id}` | Full document with signer data |
| `GET /api/document/{id}/pdf` | DOU-style PDF download |
| `GET /api/autocomplete?q=...` | Search suggestions |
| `GET /api/trending` | Dynamic trending topics |
| `GET /api/stats` | Corpus statistics (total, date range) |
| `GET /api/types` | Available art_type facets with counts |
| `GET /api/health` | Service health check |

### Search Response

```json
{
  "results": [...],
  "total": 6977,
  "query": "LGPD",
  "took_ms": 27,
  "intent": {
    "detected": "canonical_lookup",
    "confidence": 0.95,
    "matched_alias": "lgpd"
  }
}
```

## PDF Generation

`GET /api/document/{id}/pdf` generates an A4 PDF mimicking the printed DOU:

- Coat of arms SVG header
- "REPÚBLICA FEDERATIVA DO BRASIL / DIÁRIO OFICIAL DA UNIÃO"
- Two-column body with justified text and hyphens
- CONSIDERANDO labels in crimson, article numbering (Art. 1º, I —)
- Signature block with signer name
- Footer: "Documento gerado por GABI DOU — gabidou.top"

Uses weasyprint with Cormorant Garamond serif font.

## Data Ingestion

### Full backfill (historical, from Liferay)

```bash
# Single year
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024

# All years
for year in $(seq 2002 2026); do
  docker compose exec -T backend python -m src.backend.ingest.sync_dou --year $year
done
```

### Daily ingest (from INLABS)

The server cron handles daily ingestion fully autonomously via a residential proxy that bypasses the INLABS WAF.

**From the server** (primary path, runs via cron at 06:00 UTC):
```bash
docker compose exec backend python -m src.backend.ingest.inlabs_daily --year 2026 --month 3
```

Requires `INLABS_PROXY=http://user:pass@host:port` in `.env` — set to a residential proxy (e.g. Webshare.io) so the INLABS WAF does not block the Hetzner datacenter IP.

**From Mac** (fallback / manual backfill only):
```bash
ops/bin/mac_daily_ingest.sh              # Last 3 days (skips existing)
ops/bin/mac_daily_ingest.sh --days 7     # Last week
ops/bin/mac_daily_ingest.sh --date 2026-03-19  # Specific day
ops/bin/mac_daily_ingest.sh --force      # Skip existence check
```

The Mac script downloads from INLABS (bypasses WAF via residential IP), SCPs ZIPs to the server, runs Mongo ingest + ES sync, and verifies counts. Use it for gap recovery or if the proxy is down.

### ES Indexer

```bash
# Incremental sync (from cursor)
docker compose exec backend python -m src.backend.ingest.es_indexer sync

# Full reindex
docker compose exec backend python -m src.backend.ingest.es_indexer backfill

# Stats
docker compose exec backend python -m src.backend.ingest.es_indexer stats
```

### TCU CSV → Postgres (raw colunar)

Reingest direto dos CSV do [portal de dados abertos do TCU](https://sites.tcu.gov.br/dados-abertos/) para tabelas `raw.*_raw` **colunares** (uma coluna por cabeçalho do CSV). Cobre acórdãos completos (por ano), jurisprudência selecionada, resposta a consulta, súmulas, três boletins e `norma.csv`. **Não** substitui ingest por scraping de BTCU ou publicações institucionais.

Defina `POSTGRES_URL` (ex.: `postgresql://gabi:gabi@postgres:5432/gabi` no compose).

```bash
# DDL + tabela de meta (primeira vez)
docker compose exec backend python -m src.backend.ingest.tcu_csv_postgres_ingest --ddl-only

# Uma fonte (ex.: súmulas)
docker compose exec backend python -m src.backend.ingest.tcu_csv_postgres_ingest --source sumula

# Todas as fontes CSV + acórdãos por ano (cache persistente recomendado em volume)
docker compose exec backend python -m src.backend.ingest.tcu_csv_postgres_ingest \
  --all --year-from 1992 --year-to 2026 --skip-unchanged \
  --cache-dir /data/gabi_dou/tcu_csv_cache

# Validar cabeçalhos dos CSV contra o catálogo (deteção de drift do TCU)
docker compose exec backend python ops/validate_tcu_csv_postgres.py --headers-only

# Contagens no Postgres vs valores esperados (~tolerância 2%)
docker compose exec backend python ops/validate_tcu_csv_postgres.py --counts-only
```

**Schema antigo:** se `raw.tcu_*_raw` tiver sido criada só com `(id, all_fields, …)`, `CREATE TABLE IF NOT EXISTS` **não** altera colunas — é preciso `DROP TABLE` dessas tabelas antes da primeira carga colunar (ou outro nome de tabela).

**Testes unitários (no container):**

```bash
docker compose exec backend python -m pytest tests/unit/test_tcu_csv_raw.py -v
```

Exemplo de cron: [`ops/cron/tcu_csv_postgres.cron.example`](ops/cron/tcu_csv_postgres.cron.example).

### Search Baseline (S0-1)

Run the search-only baseline against `/api/search` and write a versioned JSON artifact:

```bash
python3 ops/baseline_search.py --base-url http://localhost:8001
```

Inputs and output:
- Query set: `ops/baselines/queries_v1.json`
- Output file: `ops/baselines/baseline_YYYYMMDD_<commit>.json`

Baseline JSON schema (minimum):
- `timestamp`, `commit`, `api_base`, `query_set_id`, `runs`
- `summary` with `latency_ms_p50`, `latency_ms_p95`, `error_rate`, `empty_rate`
- `summary.results_count_histogram` and `summary.total_histogram`
- `per_query` aggregated stats

Exit behavior:
- Returns `0` when all samples succeed
- Returns non-zero when any query/run fails (still writes the JSON report)

## Server Crons

| Schedule | Task |
|----------|------|
| 06:00 UTC | Daily INLABS ingest (`run_daily_ingest.sh`) |
| 07:00 UTC | ES reconciliation (`reconcile_es.sh`) |
| 09:00 America/Sao_Paulo | Homepage cache refresh (`update_homepage_cache.sh`) |
| 08:00 UTC | Temp file cleanup (`/tmp/gabi_*`) |

## ES Index

Index: `gabi_documents_v3` (alias: `gabi_documents`)

Key fields:
- `identifica` (text, pt_folded) — document title
- `ementa` (text, pt_folded) — summary
- `body_plain` (text, pt_folded) — full text
- `art_type_normalized` (keyword, lowercase) — "lei", "portaria", "decreto"
- `document_number` (keyword) — "13.709", "234"
- `document_year` (integer) — 2018, 2026
- `issuing_organ` (text, pt_folded) — issuing authority
- `primary_signer` (text) — document signer
- `pub_date` (date) — publication date
- `section` (keyword) — DOU section (do1, do2, do3)

Analyzer `pt_folded`: standard tokenizer + lowercase + asciifolding.

## Frontend

- **Light mode** default, dark mode via toggle (persists in localStorage)
- **Intent badges** on search results ("📜 Lei", "📅 Recentes", "🔍 Tema", "👤 Pessoa")
- **"Você quis dizer?"** suggestions for partial canonical matches
- **Trending chips** on homepage with trend score indicators (🔥, ↗)
- **"Atualizado até"** date below search bar
- **PDF download** button in document viewer (header + actions sheet)
- **Responsive** design (mobile-first with bottom sheets)

## Production Deployment

```bash
# On Hetzner server
cd /home/gabi/gabi-kimi
git pull origin main
docker compose up -d --build

# HTTPS via host nginx + certbot
# See ops/nginx/ for config
```

### Domain

- Domain: `gabidou.top` (Namesilo → Hetzner 204.168.173.163)
- HTTPS: Let's Encrypt via certbot (auto-renewal)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_STRING` | `mongodb://mongo:27017/gabi_dou` | MongoDB connection |
| `ES_URL` | `http://elasticsearch:9200` | Elasticsearch URL |
| `ES_INDEX` | `gabi_documents_v3` | ES index name |
| `VECTOR_SEARCH_ENABLED` | `false` | Enable kNN vector search |
| `RERANKER_ENABLED` | `false` | Enable neural reranker |
| `INLABS_USER` | — | INLABS login email |
| `INLABS_PWD` | — | INLABS password |
| `INLABS_PROXY` | — | Residential proxy URL (`http://user:pass@host:port`) to bypass INLABS WAF on Hetzner |
| `POSTGRES_URL` | `postgresql://gabi:gabi@postgres:5432/gabi` | Postgres (raw archive / TCU CSV reingest) |

## Project Structure

```
src/
  backend/
    core/config.py          # Settings
    data/
      db.py                 # MongoDB connection
      canonical_laws.json   # 30+ popular law names → formal refs
    ingest/
      inlabs_daily.py       # Daily INLABS ingestion
      sync_dou.py           # Historical Liferay ingestion
      dou_processor.py      # XML parsing → documents
      es_indexer.py          # MongoDB → ES sync
      es_reconcile.py        # ES ↔ Mongo consistency check
      tcu_csv_postgres_ingest.py  # TCU open data CSV → Postgres raw (colunar)
      tcu_csv_raw_catalog.py   # URLs + colunas esperadas por CSV
    pdf/
      template.py           # DOU-style HTML template
      generator.py          # weasyprint HTML→PDF
    search/
      hybrid.py             # Query classification + ES execution
      intent.py             # Intent classifier (5 types)
      query_builders.py     # ES query DSL per intent
      trending.py           # Trending computation + cache
      reranker.py           # Neural reranker client (disabled)
    main.py                 # FastAPI app + endpoints
  frontend/app/
    src/
      pages/
        HomePage.tsx        # Landing with trending + stats
        SearchPage.tsx      # Results with intent badges
        DocumentPage.tsx    # Full document view + PDF button
      components/
        ThemeToggle.tsx     # Light/dark mode toggle
        SearchBar.tsx       # Autocomplete search input
        ResultCard.tsx      # Search result card
      lib/api.ts            # API types + fetch functions
ops/
  bin/
    mac_daily_ingest.sh     # Mac→server ingest relay
    run_daily_ingest.sh     # Server-side daily cron
    update_homepage_cache.sh # Refresh homepage trending + editorial cache
  validate_tcu_csv_postgres.py  # Headers / counts vs catalog (TCU CSV raw)
  cron/
    tcu_csv_postgres.cron.example  # Cron sugerido p/ reingest CSV → Postgres
  container/
    frontend-prod.sh        # npm build + preview
    backend-prod.sh         # uvicorn production
  nginx/prod.conf           # Container nginx config
docs/
  search-quality-research.md  # Reranker vs BM25 evaluation
```

## Search Quality Research

A triangular consensus panel (qwen3-max, kimi-k2.5, claude-sonnet-4.5) evaluated whether to enable neural re-ranking. Verdict: **optimize BM25 first**, defer reranker until infrastructure upgrade (≥32GB RAM). See `docs/search-quality-research.md`.

## MCP (Model Context Protocol)

GABI exposes 20 search and evidence tools via MCP, allowing AI assistants to query DOU and TCU data programmatically.

Two transports are available:

### SSE (Server-Sent Events) — for Claude Code, Cursor, etc.

```json
{
  "mcpServers": {
    "gabi-dou": {
      "type": "sse",
      "url": "https://gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

CLI setup:
```bash
claude mcp add --transport sse gabi-dou https://gabidou.top/mcp/sse \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

### Streamable HTTP — for Codex, newer MCP clients

```json
{
  "mcpServers": {
    "gabi-dou": {
      "serverUrl": "https://gabidou.top/mcp-http/",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

### Available tool groups

| Group | Tools | Description |
|-------|-------|-------------|
| Search | `es_search` | Canonical search entry point for DOU, TCU, BTCU, and TCU Publicações (`source: dou/tcu/tcu_normas/all/btcu/publicacoes`) |
| Discover | `es_more_like_this`, `es_significant_terms`, `es_cross_reference` | Similar docs, themes, citation network |
| Analyze | `es_timeline`, `es_trending`, `es_organ_profile`, `es_compare_periods` | Temporal trends, institutional analysis |
| TCU Semantic | `es_tcu_semantic_search`, `es_tcu_similar` | kNN vector search on TCU embeddings (source: tcu/normas/btcu/all) |
| Evidence | `es_evidence_bundle`, `es_parent_expand`, `es_audit_query` | Citation-ready retrieval, parent context expansion, retrieval audit lookup |
| Compatibility | `es_btcu_search`, `es_publicacoes_search` | Backward-compatible wrappers over `es_search` |
| Utility | `es_suggest`, `es_facets`, `es_document`, `es_health`, `es_explain` | Autocomplete, aggregations, fetch, health, debugging |

### Traditional stdio server

Run the MCP server directly in stdio mode:

```bash
./ops/bin/run_mcp_server.sh
```

Run the standalone SSE server on a custom port:

```bash
./ops/bin/run_mcp_server.sh --transport sse --port 8766
```

### MCP quality benchmark

Run the curated MCP quality harness to verify real search usefulness, not just tool contracts:

```bash
docker compose exec backend python ops/eval_mcp_quality.py
docker compose exec backend python ops/eval_mcp_quality.py --case lgpd
docker compose exec backend python ops/eval_mcp_quality.py --strict-optional
```

This writes:
- `ops/eval_mcp_quality_results.json`
- `ops/eval_mcp_quality_report.md`

When the source is unknown, start with `es_search` and omit `source`. GABI now federates across DOU, TCU acórdãos, TCU normas, BTCU, and Publicações by default, and returns a `source_breakdown` summary plus normalized per-hit source metadata. Reach for `es_evidence_bundle` after search when you need citation-ready evidence, and only then move to specialist tools like `es_tcu_semantic_search`, `es_cross_reference`, or `es_explain`.

Treat benchmark output as an ops artifact, not repo state: generate the JSON/Markdown report during deploy validation and archive it in ops notes or release notes instead of committing it.

## Hosted Dev-Converge

Multi-agent consensus and synthesis service hosted at `converge.gabidou.top`. Runs as a separate FastAPI container (`dev-converge-api`) on port 8011, independent from the main GABI backend.

### Design: stateless credentials

The server holds **no provider keys**. Every request carries the full agent catalog in a required header:

```
X-Dev-Converge-Agents: <base64url-encoded JSON>
```

Payload format:

```json
{
  "agents": [
    {
      "name": "kimi",
      "provider": "openai_compatible",
      "model": "kimi-k2.5",
      "api_key": "sk-...",
      "base_url": "https://coding-intl.dashscope.aliyuncs.com/v1"
    },
    {
      "name": "claude",
      "provider": "anthropic_compatible",
      "model": "claude-sonnet-4-6",
      "api_key": "sk-ant-...",
      "base_url": ""
    },
    {
      "name": "gemini",
      "provider": "gemini_compatible",
      "model": "gemini-2.0-flash",
      "api_key": "AIza...",
      "base_url": ""
    }
  ],
  "default_synthesizer": "kimi"
}
```

Supported `provider` values: `openai_compatible`, `anthropic_compatible`, `gemini_compatible`. Any endpoint that follows one of these three API contracts works — Alibaba/DashScope, Qwen, Minimax, OpenAI, Anthropic, Gemini, etc.

### Endpoints

| Transport | URL |
|-----------|-----|
| SSE (Claude Code, Cursor) | `https://converge.gabidou.top/mcp/sse` |
| Streamable HTTP (Codex, newer clients) | `https://converge.gabidou.top/mcp-http/` |
| Health | `https://converge.gabidou.top/api/health` |

Auth: `Authorization: Bearer <DEV_CONVERGE_API_TOKENS value>`

### Local client setup

Set provider credentials and model lists in `.env` (see `.env.example` for all keys):

```bash
# OpenAI direct (uses max_completion_tokens — NOT max_tokens)
OPENAI_API_KEY=sk-proj-...
OPENAI_API_MODELS=gpt-5.4-2026-03-05

# Anthropic direct
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_API_MODELS=claude-sonnet-4-6

# Gemini compatible
GEMINI_API_KEY=AIza...
GEMINI_API_MODELS=gemini-3.1-pro-preview

# DashScope openai_compatible (uses max_tokens)
DASHSCOPE_API_KEY=sk-sp-...
DASHSCOPE_API_MODELS=kimi-k2.5;MiniMax-M2.5;qwen3-max-2026-01-23;glm-5  # semicolon-separated

DEV_CONVERGE_API_TOKENS=label:your-bearer-token
```

Provider types: `openai` (direct, max_completion_tokens), `openai_compatible` (DashScope, max_tokens), `anthropic` (direct), `anthropic_compatible`, `gemini_compatible`.

Then run the setup script:

```bash
python3 gen_converge_mcp.py --apply        # encode catalog + update .mcp.json
python3 gen_converge_mcp.py --header-only  # print just the header value (for IDE copy-paste)
python3 gen_converge_mcp.py --header-only | pbcopy  # macOS: copy directly to clipboard
```

Re-run `--apply` whenever you rotate keys or change the model list. The script also accepts `--env path/to/.env` for non-default locations.

For IDEs that load static JSON (VSCode, Trae, Cursor, Windsurf), use `--header-only` to get the value to paste into `X-Dev-Converge-Agents`. See `docs/mcp-setup.md` for per-IDE config examples.

The resulting `.mcp.json` entry looks like:

```json
{
  "mcpServers": {
    "dev-converge": {
      "url": "https://converge.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer <token>",
        "X-Dev-Converge-Agents": "<base64url catalog>"
      }
    }
  }
}
```

### Tools (11 total)

| Tool | Type | Description |
|------|------|-------------|
| `get_defaults` | sync | Service capabilities and required header format |
| `ping_models` | sync | Health check — call all catalog agents |
| `complete_once` | sync | Single agent completion (requires `agent_name` if catalog > 1) |
| `run_panel` | sync | Parallel multi-agent analysis + local synthesis |
| `swarm_panel` | sync | Cooperative swarm with assigned roles |
| `jury_panel` | sync | Expert witnesses + jury verdict |
| `triangular_panel` | sync | 3-phase: analysis → critique → revision |
| `start_run_panel` | async | Enqueue run_panel job, returns `job_id` |
| `start_swarm_panel` | async | Enqueue swarm_panel job |
| `start_jury_panel` | async | Enqueue jury_panel job |
| `poll_job` | — | Poll async job status and retrieve result |

### Async job lifecycle

`start_*` tools enqueue the job in an **in-memory asyncio queue** inside the API process. Job metadata (status, agents used, result preview) is persisted to MongoDB. Raw API keys are never written to Mongo or disk — only agent name, provider, model, and base URL are stored.

On restart, any in-flight jobs are marked `failed` with `reason: service_restart`. Completed results remain accessible via `poll_job` for `DEV_CONVERGE_JOB_RETENTION_HOURS` (default 168h).

### Dynamic timeout

Panel tools auto-calculate a timeout per call:

```
timeout = max(60, min(600, 60 × num_agents × rounds))
```

| Scenario | Auto-timeout |
|----------|-------------|
| 4 agents, 1 round | 240s |
| 7 agents, 1 round | 420s → capped at 600s |
| 3 agents, 2 rounds | 360s |
| 1 agent | 60s (minimum) |

Override with `timeout_sec` on any tool (e.g. `timeout_sec=900` for a very long panel). For jobs that exceed the sync timeout, use `start_run_panel` + `poll_job` instead.

### Key environment variables

| Variable | Description |
|----------|-------------|
| `DEV_CONVERGE_API_TOKENS` | Bearer tokens: `label:token,label2:token2` |
| `DEV_CONVERGE_MONGO_STRING` | MongoDB connection (must include auth in prod) |
| `DEV_CONVERGE_SITE_URL` | Public URL for DNS rebinding protection |
| `DEV_CONVERGE_ALLOWED_HOSTS` | Comma-separated allowed Host headers |
| `DEV_CONVERGE_SYNC_TIMEOUT_SEC` | Fallback timeout for sync calls without auto-calc (default 180s) |
| `DEV_CONVERGE_MAX_PARALLEL_AGENTS` | Max concurrent agent calls per job (default 4) |
| `DEV_CONVERGE_DATA_ROOT` | Artifact storage root (default `/data/dev_converge`) |

### Source layout

```
src/dev_converge/
  config.py      — Settings (no provider keys)
  providers.py   — decode_catalog(), build_agent(), call_agent() for 5 provider types:
                    openai (max_completion_tokens), openai_compatible (max_tokens),
                    anthropic, anthropic_compatible, gemini_compatible
  executor.py    — Panel execution patterns; all accept runtime catalog
  mcp_server.py  — FastMCP tools, auth + X-Dev-Converge-Agents header decode
  jobs.py        — MongoDB job queue (redacted metadata only)
  worker.py      — In-process asyncio queue + maintenance loop
  main.py        — FastAPI app, lifespan starts worker + stale-job cleanup
```

### Production deploy

```bash
# On Hetzner server
cd /home/gabi/gabi-kimi
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build dev-converge-api
```

### Local smoke test

```bash
docker compose exec dev-converge-api python ops/test_dev_converge_tools.py
```

### Live test results (2026-03-30)

All 7 catalog agents confirmed responding:

**ping_models — all agents reachable:**

| Agent | Provider | Latency |
|-------|----------|---------|
| gpt-5.4-2026-03-05 | openai | 1828ms |
| claude-sonnet-4-6 | anthropic | 1056ms |
| gemini-3.1-pro-preview | gemini_compatible | 4061ms |
| kimi-k2.5 | openai_compatible | 2018ms |
| MiniMax-M2.5 | openai_compatible | 3555ms |
| qwen3-max-2026-01-23 | openai_compatible | 3057ms |
| glm-5 | openai_compatible | 5054ms |

**run_panel — DOU compliance question (4-agent subset):**
- Task: "A Brazilian federal agency needs to publish a new regulation in the DOU. List the 3 most critical compliance requirements they must follow, and one concrete mitigation for each."
- Agents: gpt-5.4-2026-03-05, claude-sonnet-4-6, kimi-k2.5, qwen3-max-2026-01-23
- Result: All 4 responded with distinct, substantive answers. Consensus converged on: (1) legal basis/competency + Nota Jurídica from CONJUR, (2) AIR + public consultation under Decreto 10.411/2020, (3) formatting/LAI metadata compliance. Each agent cited different specific laws (Art. 2º Lei 9.784/99, Decreto 7.724/2012, IN SAD/PR 1/2020) showing diversity of knowledge.

**swarm_panel — microservices vs monolith (7-agent):**
- Task: "A developer asks: should I use microservices or a monolith for a small team?"
- Roles: architect, devops, backend_developer
- Result: 7/7 agents responded. Strong consensus: **start with a modular monolith**. Key themes: cognitive load limit for small teams, operational tax of microservices, YAGNI principle. Notable: kimi-k2.5 produced an ASCII architecture diagram; claude-sonnet-4-6 included a team-size decision table; glm-5 framed microservices as solving organizational (not technical) scaling problems.

**Key fixes validated:**
- `gpt-5.4-2026-03-05` — was returning HTTP 400 due to `max_tokens`; now works with `max_completion_tokens` via `openai` provider type
- `return_exceptions=True` in `asyncio.gather` — one agent failure no longer aborts the entire panel
- Provider taxonomy: `openai` (direct), `openai_compatible` (DashScope), `anthropic` (direct), `anthropic_compatible`, `gemini_compatible`

## Backlog

Open issues tracked in `.planning/todos/pending/`:
- Reranker CPU deployment (insufficient RAM)
- Disk monitoring (volume at 84%)
- ES reconciliation optimization
