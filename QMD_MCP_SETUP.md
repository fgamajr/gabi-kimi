# QMD MCP Server Setup

## Installation Summary

QMD has been installed and configured as an MCP server for this project.

### What is QMD?

QMD is a local search engine for markdown documents that combines:
- **BM25** full-text search (keyword-based)
- **Vector** semantic search (meaning-based)
- **LLM re-ranking** (best quality results)

All running locally via `node-llama-cpp` with GGUF models.

## Configuration

**MCP Server Config:** `.qwen/mcp.json`

```json
{
  "mcpServers": {
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
```

## Quick Start

### 1. Add Collections

Index your markdown files (docs, notes, meeting transcripts):

```bash
# Add current project docs
qmd collection add ./docs --name docs
qmd collection add ./analysis --name analysis

# Add global context
qmd context add qmd://docs "Project documentation and guides"
qmd context add qmd://analysis "Analysis and research notes"
```

### 2. Generate Embeddings

```bash
# Create vector embeddings for semantic search
qmd embed
```

### 3. Search

```bash
# Keyword search (fast)
qmd search "API documentation"

# Semantic search (meaning-based)
qmd vsearch "how to use the XML ingestion pipeline"

# Hybrid search with re-ranking (best quality)
qmd query "DOU extraction pipeline"

# Get specific document
qmd get "docs/architecture.md"

# Get multiple documents
qmd multi-get "docs/*.md"
```

## MCP Tools Available

Once connected, the following tools are available to AI agents:

| Tool | Description |
|------|-------------|
| `qmd_search` | Fast BM25 keyword search |
| `qmd_vector_search` | Semantic vector search |
| `qmd_deep_search` | Deep search with query expansion + reranking |
| `qmd_get` | Retrieve document by path or docid |
| `qmd_multi_get` | Retrieve multiple documents by glob pattern |
| `qmd_status` | Index health and collection info |

## Data Storage

- **Index:** `~/.cache/qmd/index.sqlite`
- **Models:** `~/.cache/qmd/models/` (auto-downloaded)
- **Cache:** `~/.cache/qmd/`

## Models Used

| Model | Purpose | Size |
|-------|---------|------|
| `embeddinggemma-300M` | Vector embeddings | ~300MB |
| `qwen3-reranker-0.6b` | Re-ranking | ~640MB |
| `qmd-query-expansion-1.7B` | Query expansion | ~1.1GB |

First run will download models automatically.

## Advanced Usage

### HTTP Transport Mode

For a shared, long-running server (avoids repeated model loading):

```bash
# Start HTTP server (default port 8181)
qmd mcp --http

# Custom port
qmd mcp --http --port 8080

# Background daemon
qmd mcp --http --daemon

# Stop daemon
qmd mcp stop
```

### Search Options

```bash
# Limit results
qmd query -n 10 "topic"

# Minimum score threshold
qmd query --min-score 0.3 "topic"

# Filter by collection
qmd search "API" -c docs

# Output formats
qmd search --json "topic"    # JSON output
qmd search --files "topic"   # File list with scores
qmd search --md "topic"      # Markdown output
```

### Index Maintenance

```bash
# Check status
qmd status

# Re-index all collections
qmd update

# Force re-embed all documents
qmd embed -f

# Cleanup cache
qmd cleanup
```

## Example Workflow

```bash
# 1. Index your docs
cd ~/projects/gabi-kimi
qmd collection add . --name gabi
qmd context add qmd://gabi "GABI project - DOU bulk XML ingestion and commitment scheme"

# 2. Generate embeddings
qmd embed

# 3. Search
qmd query "CRSS-1 commitment scheme"
qmd vsearch "how does the XML ingestion pipeline work"
qmd search --json "extraction harness" -n 5
```

## Troubleshooting

### Models not downloading
Check internet connection and HuggingFace accessibility.

### SQLite errors on Linux
Ensure SQLite with FTS5 support is installed:
```bash
# Ubuntu/Debian
sudo apt-get install sqlite3 libsqlite3-dev

# macOS
brew install sqlite
```

### Slow first search
First search loads models into memory (~30s). Subsequent searches are fast.
Use HTTP daemon mode for persistent server.

## Resources

- **GitHub:** https://github.com/tobi/qmd
- **CHANGELOG:** https://github.com/tobi/qmd/blob/main/CHANGELOG.md
- **Docs:** Run `qmd --help` for CLI reference
