# GABI DOU — Busca Inteligente no Diário Oficial da União

**[gabidou.top](https://gabidou.top)** — Full-text search over ~16M Brazilian government gazette documents (2002–2026), with intent-based ranking, PDF generation, and dynamic trending.

## Live System

- **15.8M+ documents** indexed from the Diário Oficial da União
- **Intent-based search**: queries automatically classified as exact name, canonical law, person name, trending, or thematic exploration
- **PDF generation**: DOU-style A4 PDFs with coat of arms, two-column layout, serif typography
- **Light/dark mode** with system preference detection

## Architecture

```
INLABS (in.gov.br)
    ↓  inlabs_daily.py (Mac relay or server cron)
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

### Dynamic Trending

`GET /api/trending` returns curated topics with publication counts. Updated by cron at 06:30 UTC. Homepage shows "Em alta no DOU" chips with trend indicators.

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

**From the server** (if INLABS WAF allows):
```bash
# Cron at 06:00 UTC
docker compose exec backend python -m src.backend.ingest.inlabs_daily --year 2026 --month 3
```

**From Mac** (INLABS WAF blocks Hetzner IP):
```bash
# Shortcut in repo root
./ingest.sh              # Last 3 days (skips existing)
./ingest.sh --days 7     # Last week
./ingest.sh --date 2026-03-19  # Specific day
./ingest.sh --force      # Skip existence check
```

The Mac script (`ops/bin/mac_daily_ingest.sh`):
1. Checks ES for which days have docs (skips existing)
2. Downloads ZIPs from INLABS (Mac not blocked by WAF)
3. SCPs ZIPs to server
4. Processes in backend container (MongoDB upsert with deduplication)
5. Runs ES incremental sync
6. Verifies final counts

### ES Indexer

```bash
# Incremental sync (from cursor)
docker compose exec backend python -m src.backend.ingest.es_indexer sync

# Full reindex
docker compose exec backend python -m src.backend.ingest.es_indexer backfill

# Stats
docker compose exec backend python -m src.backend.ingest.es_indexer stats
```

## Server Crons

| Schedule | Task |
|----------|------|
| 06:00 UTC | Daily INLABS ingest (`run_daily_ingest.sh`) |
| 07:00 UTC | ES reconciliation (`reconcile_es.sh`) |
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

GABI exposes 15+ search tools via MCP, allowing AI assistants to query DOU and TCU data programmatically.

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
| Search | `es_search` | Hybrid BM25 + kNN with intent detection (source: dou/tcu/tcu_normas/all) |
| Discover | `es_more_like_this`, `es_significant_terms`, `es_cross_reference` | Similar docs, themes, citation network |
| Analyze | `es_timeline`, `es_trending`, `es_organ_profile`, `es_compare_periods` | Temporal trends, institutional analysis |
| TCU Semantic | `es_tcu_semantic_search`, `es_tcu_similar` | kNN vector search on TCU embeddings (source: tcu/normas/btcu/all) |
| Utility | `es_suggest`, `es_facets`, `es_document`, `es_health`, `es_explain` | Autocomplete, aggregations, debugging |

## Backlog

Open issues tracked in `.planning/todos/pending/`:
- INLABS WAF blocks Hetzner IP (Mac relay workaround active)
- Reranker CPU deployment (insufficient RAM)
- Disk monitoring (volume at 84%)
- ES reconciliation optimization
