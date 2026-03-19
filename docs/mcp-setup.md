# GABI DOU — MCP Server Setup Guide

Connect your AI coding assistant to GABI's 16M+ DOU document search engine.

## Supported Clients

| Client | Transport | Config File |
|--------|-----------|-------------|
| Claude Code (CLI) | stdio | `~/.claude/projects/.../settings.json` |
| Claude Desktop | stdio | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Cursor | stdio | `~/.cursor/mcp.json` |
| VS Code (Copilot) | stdio | `~/Library/Application Support/Code/User/mcp.json` |
| Windsurf | stdio | `~/.windsurf/mcp.json` |
| Zed | stdio | `~/.config/zed/settings.json` |
| Remote clients | SSE | HTTP endpoint (see below) |

## Prerequisites

```bash
# From the repo root
pip install mcp httpx python-dotenv

# Verify it works
python3 ops/bin/mcp_es_server.py --help
```

The MCP server needs access to:
- **Elasticsearch** at `ES_URL` (for analytics tools)
- **GABI FastAPI backend** at `GABI_API_URL` (for search/suggest/document)

## Configuration by Client

### Claude Code (CLI)

Already configured if you cloned this repo. The config is at `.claude/projects/-Users-.../settings.json`:

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
        "GABI_API_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gabi-dou": {
      "command": "python3",
      "args": ["/absolute/path/to/gabi-kimi/ops/bin/mcp_es_server.py"],
      "env": {
        "ES_URL": "http://localhost:9200",
        "ES_ALIAS": "gabi_documents",
        "GABI_API_URL": "http://localhost:8001",
        "GABI_API_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Cursor

Edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "gabi-dou": {
      "command": "python3",
      "args": ["/absolute/path/to/gabi-kimi/ops/bin/mcp_es_server.py"],
      "env": {
        "ES_URL": "http://localhost:9200",
        "ES_ALIAS": "gabi_documents",
        "GABI_API_URL": "http://localhost:8001",
        "GABI_API_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### VS Code (GitHub Copilot)

Edit `~/Library/Application Support/Code/User/mcp.json`:

```json
{
  "servers": {
    "gabi-dou": {
      "command": "python3",
      "args": ["/absolute/path/to/gabi-kimi/ops/bin/mcp_es_server.py"],
      "env": {
        "ES_URL": "http://localhost:9200",
        "ES_ALIAS": "gabi_documents",
        "GABI_API_URL": "http://localhost:8001",
        "GABI_API_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Windsurf

Edit `~/.windsurf/mcp.json` (same format as Cursor):

```json
{
  "mcpServers": {
    "gabi-dou": {
      "command": "python3",
      "args": ["/absolute/path/to/gabi-kimi/ops/bin/mcp_es_server.py"],
      "env": {
        "ES_URL": "http://localhost:9200",
        "ES_ALIAS": "gabi_documents",
        "GABI_API_URL": "http://localhost:8001",
        "GABI_API_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Zed

Edit `~/.config/zed/settings.json`, add inside `"context_servers"`:

```json
{
  "context_servers": {
    "gabi-dou": {
      "command": {
        "path": "python3",
        "args": ["/absolute/path/to/gabi-kimi/ops/bin/mcp_es_server.py"]
      },
      "settings": {}
    }
  }
}
```

Note: Zed passes env vars from the shell environment. Export them in your `.zshrc`/`.bashrc`:

```bash
export ES_URL=http://localhost:9200
export GABI_API_URL=http://localhost:8001
export GABI_API_TOKEN=YOUR_TOKEN_HERE
```

### Remote Clients (SSE Transport)

For clients that can't run local processes, start the MCP server as an HTTP endpoint:

```bash
python3 ops/bin/mcp_es_server.py --transport sse --port 8766
```

Connect via `http://YOUR_SERVER:8766/sse`. Set `MCP_AUTH_TOKEN` to require bearer auth from connecting clients.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ES_URL` | `http://elasticsearch:9200` | Elasticsearch URL |
| `ES_ALIAS` | `gabi_documents` | ES index/alias name |
| `GABI_API_URL` | `http://localhost:8001` | FastAPI backend URL |
| `GABI_API_TOKEN` | _(empty)_ | Bearer token for FastAPI auth |
| `MCP_AUTH_TOKEN` | _(empty)_ | Bearer token required from SSE clients |

## Authentication

The GABI API uses bearer token auth. To get a token, ask the project admin to add an entry to `GABI_API_TOKENS` in the server's `.env`:

```
GABI_API_TOKENS=mcp:TOKEN1,yourname:TOKEN2
```

Each entry is `label:token`. You'll receive your token value to put in `GABI_API_TOKEN`.

**Without a token:** Search, autocomplete, and document fetching still work (the API allows unauthenticated browser requests). But if you send an invalid token, you'll get 401.

## Available Tools (13)

### Search (proxied through hybrid pipeline)

| Tool | Description |
|------|-------------|
| `es_search` | Full hybrid search: BM25 + kNN, intent detection, topic classification, person names, quoted phrases, canonical law lookup |
| `es_suggest` | Autocomplete suggestions |
| `es_document` | Fetch full document by ID |

### Analytics (direct Elasticsearch)

| Tool | Description |
|------|-------------|
| `es_facets` | Section/type/organ aggregations + date histogram |
| `es_more_like_this` | Find similar documents |
| `es_significant_terms` | Discover significant terms in a result set |
| `es_timeline` | Date histogram for temporal analysis |
| `es_trending` | Top trending topics in recent days |
| `es_cross_reference` | Find documents citing a legal reference |
| `es_organ_profile` | Statistics for an issuing organ |
| `es_compare_periods` | Compare document volumes between two periods |
| `es_explain` | Debug why a document ranked where it did |
| `es_health` | Cluster health and index statistics |

## Usage Examples

Once connected, you can ask your AI assistant:

```
"Search for concursos públicos federais from 2024"
→ uses es_search with intent detection

"Find documents about LGPD by ANPD"
→ uses es_search with canonical law lookup

"Show me trending topics in the last 7 days"
→ uses es_trending

"How many portarias did Ministério da Saúde publish in 2025?"
→ uses es_facets or es_organ_profile

"Find documents similar to this one: <doc_id>"
→ uses es_more_like_this

"Compare licitações volume between Jan 2025 and Jan 2026"
→ uses es_compare_periods
```

### Topic Filter

Use the `topic` parameter in `es_search` to filter by document classification:

```
es_search(query="edital", topic="concurso_selecao")
es_search(query="resolução", topic="saude")
es_search(query="portaria", topic="regulacao_norma")
```

Available topics: `concurso_selecao`, `licitacao_compras`, `contrato_convenio`, `pessoal_rh`, `regulacao_norma`, `consulta_participacao`, `saude`, `educacao`, `meio_ambiente`, `financeiro`, `energia_telecom`, `administrativo`.

## Troubleshooting

**"mcp package is not installed"**
```bash
pip install mcp
```

**Connection refused to ES or API**
- Check if Docker containers are running: `docker ps`
- Check ES: `curl http://localhost:9200/_cluster/health`
- Check API: `curl http://localhost:8001/api/health`

**401 Unauthorized**
- Your `GABI_API_TOKEN` is invalid or expired
- Ask the admin for a valid token

**Tools not appearing in your client**
- Restart the client after changing config
- Check logs: most clients show MCP connection errors in their developer console
