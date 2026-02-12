# MCP Hybrid Search Implementation Summary

## Overview

This document summarizes the complete implementation of the new **MCP Hybrid Search Server** for the GABI project, designed to replace the legacy MCP server with advanced hybrid search capabilities.

## Files Created/Modified

### 1. Core Implementation Files

| File | Description | Lines |
|------|-------------|-------|
| `src/gabi/mcp/tools_hybrid.py` | Hybrid search tools (search_exact, search_semantic, search_hybrid) | ~850 |
| `src/gabi/mcp/resources_hybrid.py` | Resource endpoints (document://, chunk://, source://, search://) | ~450 |
| `src/gabi/mcp/server_hybrid.py` | MCP server with SSE transport, auth, rate limiting | ~650 |
| `src/gabi/mcp/__init__.py` | Updated exports for new modules | ~80 |

### 2. Deployment Configuration

| File | Description |
|------|-------------|
| `docker/mcp-hybrid.Dockerfile` | Docker image for MCP Hybrid Server |
| `docker/docker-compose.mcp-hybrid.yml` | Docker Compose configuration |
| `k8s/mcp-hybrid-deployment.yaml` | Kubernetes deployment manifests |

### 3. Utilities and Documentation

| File | Description |
|------|-------------|
| `scripts/migrate_mcp_to_hybrid.py` | Migration script from legacy to hybrid |
| `docs/MCP_HYBRID_SEARCH.md` | Complete documentation |
| `tests/test_mcp_hybrid.py` | Comprehensive test suite |
| `Makefile` | Updated with MCP hybrid commands |
| `MCP_HYBRID_IMPLEMENTATION_SUMMARY.md` | This document |

## Key Features

### 1. Search Tools

#### search_exact
- **Purpose**: Exact search by specific fields
- **Document Types**: normas, acordaos, publicacoes, leis
- **Fields**: numero, ano, relator, orgao_julgador, tipo, autor, titulo, etc.
- **Backend**: Elasticsearch BM25

#### search_semantic
- **Purpose**: Meaning-based search using embeddings
- **Backend**: Elasticsearch kNN or pgvector
- **Model**: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- **Dimensions**: 384 (immutable per ADR-001)

#### search_hybrid
- **Purpose**: Combined exact + semantic with RRF
- **Algorithm**: Reciprocal Rank Fusion (RRF)
- **Formula**: `score = Σ weight/(k + rank)` where k=60
- **Weights**: Configurable BM25 and vector weights

### 2. Resources

| Resource URI | Description |
|--------------|-------------|
| `document://{id}` | Complete document |
| `document://{id}/chunks` | All chunks of a document |
| `chunk://{doc_id}/{index}` | Specific chunk |
| `source://{id}/stats` | Source statistics |
| `source://list` | List all sources |
| `search://health` | Search health check |

### 3. Security Features

- **Authentication**: JWT RS256 via Keycloak TCU
- **Authorization**: Role-based permissions (gabi-search, gabi-admin, gabi-reader)
- **Rate Limiting**: Redis-based per user/tool
- **CORS**: Configurable origins
- **Audit Logging**: All tool calls logged

### 4. Rate Limits

| Tool | Limit |
|------|-------|
| search_exact | 60/min |
| search_semantic | 30/min |
| search_hybrid | 30/min |
| get_document_details | 100/min |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ChatTCU (Client)                         │
└──────────────────────┬──────────────────────────────────────────┘
                       │ SSE Transport
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                 MCP Hybrid Search Server                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Tools     │  │  Resources  │  │    Auth/Rate Limit      │  │
│  │             │  │             │  │                         │  │
│  │ • search_   │  │ • document  │  │ • JWT Validation        │  │
│  │   exact     │  │ • chunk     │  │ • Permission Check      │  │
│  │ • search_   │  │ • source    │  │ • Redis Rate Limit      │  │
│  │   semantic  │  │ • search    │  │ • Audit Logging         │  │
│  │ • search_   │  │             │  │                         │  │
│  │   hybrid    │  │             │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│Elasticsearch│ │  PostgreSQL │ │    Redis    │
│  (BM25 +    │ │  + pgvector │ │(Rate Limit, │
│   kNN)      │ │  (Vectors)  │ │    Cache)   │
└─────────────┘ └─────────────┘ └─────────────┘
```

## API Examples

### Initialize Connection
```bash
curl -N \
  -H "Authorization: Bearer <token>" \
  http://localhost:8001/mcp/sse
```

### Search Hybrid
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  "http://localhost:8001/mcp/message?sessionId=<id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {
      "name": "search_hybrid",
      "arguments": {
        "query": "sustentabilidade fiscal",
        "document_type": "acordaos",
        "hybrid_weights": {"bm25": 1.0, "vector": 1.2},
        "limit": 10
      }
    }
  }'
```

### Read Resource
```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8001/mcp/resources/document://TCU-4567/2024"
```

## Deployment

### Docker Compose
```bash
# Start with hybrid MCP
make mcp-hybrid-docker

# Or manually
docker-compose -f docker-compose.yml -f docker/docker-compose.mcp-hybrid.yml up -d mcp-hybrid
```

### Kubernetes
```bash
kubectl apply -f k8s/mcp-hybrid-deployment.yaml
```

### Local Development
```bash
# Run locally with hot reload
make mcp-hybrid-run

# Run tests
make mcp-hybrid-test

# Check health
make mcp-hybrid-health
```

## Migration from Legacy MCP

```bash
# Check current state
make mcp-hybrid-check

# Perform migration
make mcp-hybrid-migrate

# Or manually
python scripts/migrate_mcp_to_hybrid.py --migrate
```

### Rollback
```bash
python scripts/migrate_mcp_to_hybrid.py --rollback
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GABI_MCP_ENABLED` | true | Enable MCP server |
| `GABI_MCP_PORT` | 8001 | Server port |
| `GABI_MCP_AUTH_REQUIRED` | true | Require authentication |
| `GABI_MCP_CORS_ORIGINS` | localhost:3000 | Allowed CORS origins |
| `GABI_SEARCH_RRF_K` | 60 | RRF constant |
| `GABI_SEARCH_BM25_WEIGHT` | 1.0 | BM25 weight |
| `GABI_SEARCH_VECTOR_WEIGHT` | 1.0 | Vector weight |
| `GABI_RATE_LIMIT_ENABLED` | true | Enable rate limiting |
| `GABI_RATE_LIMIT_REQUESTS_PER_MINUTE` | 60 | Rate limit per minute |

## Testing

```bash
# Run all MCP hybrid tests
pytest tests/test_mcp_hybrid.py -v

# Run specific test class
pytest tests/test_mcp_hybrid.py::TestToolManager -v

# Run with coverage
pytest tests/test_mcp_hybrid.py --cov=src/gabi/mcp --cov-report=html
```

## Performance Considerations

1. **Parallel Search**: BM25 and vector searches run in parallel
2. **Lazy Initialization**: SearchService initialized on first use
3. **Connection Pooling**: PostgreSQL and Elasticsearch connections pooled
4. **Caching**: JWKS and rate limit counters cached in Redis
5. **Timeouts**: All external calls have configurable timeouts

## Monitoring

### Health Endpoint
```bash
curl http://localhost:8001/health
```

Response:
```json
{
  "status": "healthy",
  "service": "mcp-hybrid-search",
  "version": "2.0.0",
  "sessions": 5,
  "capabilities": {
    "tools": ["search_exact", "search_semantic", "search_hybrid", ...],
    "resources": ["document://", "chunk://", "source://", "search://"]
  }
}
```

### Logs
```bash
# Docker
docker logs -f gabi-mcp-hybrid

# Kubernetes
kubectl logs -f deployment/mcp-hybrid -n gabi
```

## Security Checklist

- [x] JWT authentication with RS256
- [x] Role-based access control
- [x] Rate limiting per user/tool
- [x] CORS protection
- [x] Input validation
- [x] SQL injection prevention (via SQLAlchemy)
- [x] Audit logging
- [x] Secure headers middleware
- [x] Non-root Docker user
- [x] Read-only root filesystem (K8s)

## Future Enhancements

1. **Streaming Results**: Stream partial results for large result sets
2. **Caching Layer**: Cache frequent queries in Redis
3. **Query Suggestions**: Auto-complete and query suggestions
4. **Faceted Search**: Add aggregations/facets to search results
5. **A/B Testing**: Compare search algorithms
6. **Analytics Dashboard**: Track search usage and performance

## References

- [MCP Specification](https://modelcontextprotocol.io/spec)
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [BM25 Algorithm](https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables)
- [Vector Search](https://www.elastic.co/guide/en/elasticsearch/reference/current/knn-search.html)

## Support

For issues or questions:
1. Check the documentation: `docs/MCP_HYBRID_SEARCH.md`
2. Run diagnostics: `make mcp-hybrid-check`
3. Check logs: `make mcp-hybrid-logs`
4. Review tests: `tests/test_mcp_hybrid.py`

---

**Version**: 2.0.0  
**Last Updated**: 2026-02-11  
**Author**: GABI Team
