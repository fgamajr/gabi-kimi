# GABI DOU — MCP Server Setup Guide

Connect your AI coding assistant to GABI's 16M+ DOU document search engine.

## Quick Start (Remote — for collaborators)

Just paste this into your config file. No local setup needed.

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "gabi-dou": {
      "url": "https://gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "gabi-dou": {
      "url": "https://gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

**VS Code** (`~/Library/Application Support/Code/User/mcp.json`):
```json
{
  "servers": {
    "gabi-dou": {
      "url": "https://gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

**Windsurf** (`~/.windsurf/mcp.json`) — same as Cursor format.

Replace `YOUR_TOKEN` with the token you received from the admin. Restart your editor. 20 tools are immediately available.

---

## Available Tools (20)

### Search Tools (hybrid pipeline)

| Tool | What it does |
|------|-------------|
| `es_search` | Canonical search entry point across DOU, TCU, BTCU, and TCU Publicações |
| `es_suggest` | Autocomplete suggestions |
| `es_document` | Fetch a full document by ID (body, metadata, signatures, media) |

### Analytics Tools (Elasticsearch direct)

| Tool | What it does |
|------|-------------|
| `es_facets` | Aggregations by section, type, organ, and monthly histogram |
| `es_more_like_this` | Find similar documents to a given doc |
| `es_significant_terms` | Discover distinctive terms in a result set |
| `es_timeline` | Publication volume over time for a query |
| `es_trending` | Trending topics in the last N days |
| `es_cross_reference` | Find documents citing a specific law or decree |
| `es_organ_profile` | Publishing profile for a government organ |
| `es_compare_periods` | Compare query volumes between two time periods |
| `es_explain` | Debug why a document scored the way it did |
| `es_health` | Cluster health, index stats, storage |

### Evidence & audit tools

| Tool | What it does |
|------|-------------|
| `es_evidence_bundle` | Return citation-ready evidence rows with chunk and parent metadata |
| `es_parent_expand` | Expand DOU chunk IDs back into parent-document context |
| `es_audit_query` | Fetch persisted retrieval traces by query ID |

### Compatibility wrappers

| Tool | What it does |
|------|-------------|
| `es_btcu_search` | Backward-compatible BTCU wrapper over `es_search(source="btcu")` |
| `es_publicacoes_search` | Backward-compatible Publicações wrapper over `es_search(source="publicacoes")` |

---

## Usage Examples

### Searching Documents

Ask your AI assistant in natural language — it will pick the right tool automatically.

Default retrieval path for agents:
1. Start with `es_search` and omit `source` when the corpus is unknown. This now federates across DOU, TCU acórdãos, TCU normas, BTCU, and Publicações.
2. Use `es_evidence_bundle` when you need citation-ready rows and provenance.
3. Use specialist tools like `es_tcu_semantic_search`, `es_cross_reference`, and `es_explain` only after the search step narrows the corpus.

**Basic search:**
```
"Busque decretos presidenciais de 2025"
```
→ `es_search(query="decretos presidenciais", date_from="2025-01-01", date_to="2025-12-31")`

**Search by topic classification:**
```
"Encontre editais de concurso público"
```
→ `es_search(query="edital concurso", topic="concurso_selecao")`

**Exact phrase (person name):**
```
"Busque publicações mencionando Eduardo Joerke"
```
→ `es_search(query="Eduardo Joerke")` — auto-detects person name, uses phrase matching

**Quoted phrase search:**
```
"Busque exatamente 'reforma tributária' no DOU"
```
→ `es_search(query="\"reforma tributária\"")` — forces exact phrase match

**Canonical law lookup:**
```
"Encontre a LGPD no Diário Oficial"
```
→ `es_search(query="LGPD")` — detects canonical law, returns Lei 13.709/2018 first

**Specific act lookup:**
```
"Mostre a Portaria MEC 234/2026"
```
→ `es_search(query="portaria MEC 234/2026")` — exact_name intent, structured field matching

**Filter by organ:**
```
"Resoluções da ANVISA sobre medicamentos"
```
→ `es_search(query="medicamento", art_type="resolução", issuing_organ="ANVISA")`

**Trending topics:**
```
"O que está em alta no DOU esta semana?"
```
→ `es_search(query="portarias", is_trending=true)` or `es_trending(days=7)`

### Discovering Patterns

**What types of documents does an organ publish?**
```
"Perfil de publicações do Ministério da Saúde"
```
→ `es_organ_profile(organ="Ministério da Saúde")`

Returns: total docs, breakdown by art_type, monthly volume, top signers.

**Temporal trends:**
```
"Como evoluiu o volume de licitações ao longo de 2025?"
```
→ `es_timeline(query="licitação", date_from="2025-01-01", date_to="2025-12-31", interval="month")`

Returns: monthly histogram with doc counts.

**Before/after comparison:**
```
"Compare publicações sobre meio ambiente entre 2024 e 2025"
```
→ `es_compare_periods(query="meio ambiente", period_a_from="2024-01-01", period_a_to="2024-12-31", period_b_from="2025-01-01", period_b_to="2025-12-31")`

Returns: volume delta, top terms, organ changes.

**Trending this week:**
```
"Quais tópicos estão em alta nos últimos 7 dias?"
```
→ `es_trending(days=7)`

Returns: top art_types and organs by recent volume spike.

### Deep Analysis

**Find documents citing a specific law:**
```
"Quais atos citam a Lei 14.133?"
```
→ `es_cross_reference(reference="Lei 14133")`

Returns: documents that reference this law in their body text.

**Find similar documents:**
```
"Encontre documentos semelhantes a este: abc123def456"
```
→ `es_more_like_this(doc_id="abc123def456")`

Returns: documents with similar terms and structure.

**Discover distinctive terms in a set of documents:**
```
"Quais termos são mais significativos nos documentos sobre saúde pública?"
```
→ `es_significant_terms(query="saúde pública", field="body_plain")`

Returns: terms that are statistically over-represented vs. the full corpus.

**Debug search ranking:**
```
"Por que este documento aparece primeiro para 'concurso público'?"
```
→ `es_explain(query="concurso público", doc_id="abc123def456")`

Returns: score breakdown showing which fields and signals contributed.

---

## Benchmarking MCP Quality

For deploy validation and search-quality regression checks, run the curated evaluator from the backend container:

```bash
docker compose exec backend python ops/eval_mcp_quality.py
docker compose exec backend python ops/eval_mcp_quality.py --case lgpd
docker compose exec backend python ops/eval_mcp_quality.py --strict-optional
```

Outputs:
- `ops/eval_mcp_quality_results.json` — full machine-readable results
- `ops/eval_mcp_quality_report.md` — human-readable summary with failures and previews

The evaluator exercises representative DOU, TCU, BTCU, Publicações, autocomplete, facets, trending, cross-reference, semantic, and evidence-bundle flows. Optional cases are skipped by default if a source index or embedding service is unavailable; use `--strict-optional` to fail them instead.

Deploy rule: do not claim an MCP deploy improved retrieval unless this benchmark passes on production data and the report is archived outside the repo.

## Hosted Dev-Converge Setup

Separate multi-agent MCP service at `converge.gabidou.top`. Each request carries the full agent catalog in a `X-Dev-Converge-Agents` header — the server holds no provider keys.

### Step 1 — Set credentials in `.env`

```bash
# Provider keys + models (semicolon-separated for multiple models)
OPENAI_API_KEY=sk-proj-...
OPENAI_API_MODELS=gpt-5.4

ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_API_MODELS=claude-sonnet-4-6

GEMINI_API_KEY=AIza...
GEMINI_API_MODELS=gemini-2.0-flash

DASHSCOPE_API_KEY=sk-sp-...
DASHSCOPE_API_MODELS=kimi-k2.5;MiniMax-M2.5;qwen3-max-2026-01-23;glm-5

# Bearer token for the dev-converge service
DEV_CONVERGE_API_TOKENS=label:your-bearer-token
```

A provider is silently skipped if either its `API_KEY` or `API_MODELS` is missing. DashScope covers Kimi, Qwen, GLM, and MiniMax-M2.5 through the same key.

### Step 2 — Generate and apply the MCP config

```bash
python3 gen_converge_mcp.py          # dry-run: print catalog summary
python3 gen_converge_mcp.py --apply  # encode catalog + update .mcp.json
```

Re-run after any key rotation or model list change. Restart your editor afterwards.

The script defaults the synthesizer to the first Kimi model found. Override with `DEV_CONVERGE_DEFAULT_SYNTHESIZER=<agent-name>` in `.env`.

### Transports

| Client | Config format | URL |
|--------|--------------|-----|
| Claude Code, Cursor, Claude Desktop | SSE | `https://converge.gabidou.top/mcp/sse` |
| Codex, newer clients | Streamable HTTP | `https://converge.gabidou.top/mcp-http/` |
| Health check | — | `https://converge.gabidou.top/api/health` |

### Tools (11)

| Tool | Type | Description |
|------|------|-------------|
| `get_defaults` | sync | Service capabilities and required header format |
| `ping_models` | sync | Health-check all catalog agents |
| `complete_once` | sync | Single-agent completion (`agent_name` required if catalog > 1) |
| `run_panel` | sync | Parallel multi-agent analysis + synthesis |
| `swarm_panel` | sync | Cooperative swarm with assigned roles |
| `jury_panel` | sync | Expert witnesses + jury verdict |
| `triangular_panel` | sync | 3-phase: analysis → critique → revision |
| `start_run_panel` | async | Enqueue `run_panel`, returns `job_id` |
| `start_swarm_panel` | async | Enqueue `swarm_panel` |
| `start_jury_panel` | async | Enqueue `jury_panel` |
| `poll_job` | — | Poll async job status and retrieve result |

### Recommended workflow

1. `get_defaults` — confirm which agents are loaded from your catalog
2. `complete_once` — quick single-agent call
3. `run_panel` / `swarm_panel` / `jury_panel` — for multi-agent consensus
4. `start_*` + `poll_job` — for async jobs that exceed the sync timeout

### IDE setup (VSCode, Trae, Windsurf, Cursor)

IDEs load MCP configs as static JSON — they cannot run scripts or read `.env` files. You need to pre-generate the header value and paste it in directly.

**Step 1 — get the full header from the terminal:**

```bash
python3 gen_converge_mcp.py --header-only | pbcopy   # macOS: copies to clipboard
python3 gen_converge_mcp.py --header-only             # Linux/Windows: copy manually
```

The dry-run output also prints the full header under `X-Dev-Converge-Agents (full):` if you want to see what's being encoded before copying.

**Step 2 — paste into your IDE config:**

The catalog JSON that gets encoded looks like this (shown here decoded for clarity):

```json
{
  "agents": [
    {
      "name": "gpt-5.4",
      "provider": "openai_compatible",
      "model": "gpt-5.4",
      "api_key": "sk-proj-YOUR_OPENAI_KEY",
      "base_url": "https://api.openai.com/v1"
    },
    {
      "name": "claude-sonnet-4-6",
      "provider": "anthropic_compatible",
      "model": "claude-sonnet-4-6",
      "api_key": "sk-ant-YOUR_ANTHROPIC_KEY",
      "base_url": ""
    },
    {
      "name": "gemini-2.0-flash",
      "provider": "gemini_compatible",
      "model": "gemini-2.0-flash",
      "api_key": "AIzaYOUR_GEMINI_KEY",
      "base_url": ""
    },
    {
      "name": "kimi-k2.5",
      "provider": "openai_compatible",
      "model": "kimi-k2.5",
      "api_key": "sk-sp-YOUR_DASHSCOPE_KEY",
      "base_url": "https://coding-intl.dashscope.aliyuncs.com/v1"
    }
  ],
  "default_synthesizer": "kimi-k2.5"
}
```

The base64url-encoded form of that JSON is the value you paste as `X-Dev-Converge-Agents`.

**VSCode** (`~/Library/Application Support/Code/User/mcp.json`):

```json
{
  "servers": {
    "dev-converge": {
      "url": "https://converge.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_BEARER_TOKEN",
        "X-Dev-Converge-Agents": "PASTE_FULL_BASE64URL_HEADER_HERE"
      }
    }
  }
}
```

**Trae / Windsurf / Cursor** (`~/.cursor/mcp.json`, `~/.trae/mcp.json`, or IDE settings panel):

```json
{
  "mcpServers": {
    "dev-converge": {
      "url": "https://converge.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_BEARER_TOKEN",
        "X-Dev-Converge-Agents": "PASTE_FULL_BASE64URL_HEADER_HERE"
      }
    }
  }
}
```

The only difference between VSCode and the others is the top-level key (`servers` vs `mcpServers`). The header values are identical across all clients.

> **Note:** The header embeds live API keys. Treat your IDE MCP config as a secrets file — don't commit it or paste it in screenshots.

### Local smoke test

```bash
docker compose exec dev-converge-api python ops/test_dev_converge_tools.py
```

### Reading Documents

**Fetch a full document:**
```
"Mostre o conteúdo completo do documento abc123def456"
```
→ `es_document(doc_id="abc123def456")`

Returns: title, ementa, body text, issuing organ, signatures, pub date, section, page, media.

**Autocomplete while typing:**
```
"Sugira completions para 'portaria min'"
```
→ `es_suggest(prefix="portaria min")`

Returns: matching titles, organs, and act types.

### Aggregations and Facets

**Distribution by type and organ:**
```
"Qual a distribuição de tipos de ato sobre educação?"
```
→ `es_facets(query="educação")`

Returns: section counts, art_type counts, organ counts, monthly histogram.

**Scoped facets:**
```
"Facetas para portarias do Ministério da Saúde em 2025"
```
→ `es_facets(query="*", art_type="portaria", issuing_organ="Ministério da Saúde", date_from="2025-01-01", date_to="2025-12-31")`

**System health:**
```
"Como está o Elasticsearch?"
```
→ `es_health()`

Returns: cluster status, index doc count, storage, shard health.

---

## Topic Classification Filter

The `topic` parameter in `es_search` filters by document classification. Available topics:

| Topic ID | Covers |
|----------|--------|
| `concurso_selecao` | Concursos, processos seletivos, editais de seleção |
| `licitacao_compras` | Licitações, pregões, dispensas, chamamentos |
| `contrato_convenio` | Contratos, aditivos, convênios |
| `pessoal_rh` | Nomeações, exonerações, aposentadorias, designações |
| `regulacao_norma` | Leis, decretos, resoluções, instruções normativas |
| `consulta_participacao` | Consultas públicas, audiências públicas |
| `saude` | ANVISA, SUS, medicamentos, vigilância sanitária |
| `educacao` | MEC, universidades, CAPES, avaliação de cursos |
| `meio_ambiente` | IBAMA, ICMBio, licenciamento ambiental |
| `financeiro` | BCB, CVM, Receita Federal, tributos, câmbio |
| `energia_telecom` | ANEEL, ANATEL, ANP, tarifas |
| `administrativo` | Catch-all: avisos, retificações, extratos genéricos |

Example:
```
es_search(query="edital 2025", topic="concurso_selecao")
```
Returns only editais classified as concursos — excludes chamadas públicas, licitações, etc.

---

## Authentication

Ask the project admin for a token. Tokens are `label:secret` pairs stored server-side. You receive only the secret part.

- **No token in config** → search still works (public API), but some clients require it
- **Invalid token** → 401 Unauthorized
- **Valid token** → full access to all 20 tools

---

## Local Development Setup

Only needed if you run Docker locally (not for remote access).

```bash
pip install mcp httpx python-dotenv
python3 ops/bin/mcp_es_server.py --help
```

**Claude Code** — already configured at `.claude/projects/.../settings.json`:
```json
{
  "mcpServers": {
    "gabi-dou": {
      "command": "python3",
      "args": ["ops/bin/mcp_es_server.py"],
      "env": {
        "ES_URL": "http://localhost:9200",
        "ES_ALIAS": "gabi_documents",
        "GABI_API_URL": "http://localhost:8001",
        "GABI_API_TOKEN": "YOUR_TOKEN"
      }
    }
  }
}
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Tools not appearing | Restart your editor after changing the config |
| 401 Unauthorized | Token is wrong — ask admin for a new one |
| Connection timeout | Server may be restarting — wait 30s and retry |
| `mcp package not installed` | `pip install mcp` (only for local stdio mode) |
| SSE disconnects | Normal for long idle — client reconnects automatically |
