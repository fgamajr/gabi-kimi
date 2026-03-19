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

Replace `YOUR_TOKEN` with the token you received from the admin. Restart your editor. 13 tools are immediately available.

---

## Available Tools (13)

### Search Tools (hybrid pipeline)

| Tool | What it does |
|------|-------------|
| `es_search` | Full hybrid search with intent detection, topic filters, person names, quoted phrases |
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

---

## Usage Examples

### Searching Documents

Ask your AI assistant in natural language — it will pick the right tool automatically.

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
- **Valid token** → full access to all 13 tools

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
