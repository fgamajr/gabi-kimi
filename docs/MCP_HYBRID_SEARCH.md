# GABI MCP Hybrid Search Server

Model Context Protocol (MCP) Server com busca híbrida para integração com ChatTCU.

## Visão Geral

O MCP Hybrid Search Server fornece capacidades avançadas de busca em documentos jurídicos do TCU:

- **search_exact**: Busca exata por campos específicos (normas, acórdãos, publicações, leis)
- **search_semantic**: Busca semântica baseada no significado do texto
- **search_hybrid**: Busca híbrida combinando exata + semântica com RRF (Reciprocal Rank Fusion)

## Arquitetura

```
┌─────────────────┐     SSE/SSE     ┌─────────────────────────┐
│   ChatTCU       │◄───────────────►│  MCP Hybrid Search      │
│   (Cliente MCP) │                 │  Server                 │
└─────────────────┘                 └───────────┬─────────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    │                           │                           │
                    ▼                           ▼                           ▼
            ┌───────────────┐          ┌───────────────┐          ┌───────────────┐
            │ Elasticsearch │          │  PostgreSQL   │          │    Redis      │
            │   (BM25)      │          │  + pgvector   │          │ (Rate Limit)  │
            └───────────────┘          └───────────────┘          └───────────────┘
```

## Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/health` | GET | Health check do servidor |
| `/mcp/sse` | GET | Conexão SSE para mensagens do servidor |
| `/mcp/message` | POST | Envio de mensagens JSON-RPC |
| `/mcp/resources/{uri}` | GET | Acesso direto a recursos |

## Tools

### search_exact

Busca exata por campos específicos em documentos jurídicos.

**Parâmetros:**
```json
{
  "document_type": "acordaos",  // normas | acordaos | publicacoes | leis
  "fields": {
    "numero": "4567/2024",
    "ano": 2024,
    "relator": "Ministro Nome"
  },
  "sources": ["tcu_acordaos"],
  "limit": 10,
  "offset": 0
}
```

**Campos por tipo de documento:**

| Tipo | Campos Disponíveis |
|------|-------------------|
| `acordaos` | numero, ano, relator, orgao_julgador, ementa, decisao |
| `normas` | numero, ano, tipo, ementa, conteudo |
| `leis` | numero, ano, tipo, ementa, conteudo |
| `publicacoes` | titulo, autor, data_publicacao, tipo, revista |

### search_semantic

Busca semântica baseada no significado do texto usando embeddings vetoriais.

**Parâmetros:**
```json
{
  "query": "licitação pregão eletrônico",
  "document_type": "acordaos",
  "sources": ["tcu_acordaos"],
  "filters": {
    "year_from": 2020,
    "year_to": 2024,
    "relator": "Ministro Nome"
  },
  "limit": 10
}
```

### search_hybrid

Busca híbrida combinando BM25 (exata) e vetorial (semântica) com RRF.

**Parâmetros:**
```json
{
  "query": "sustentabilidade fiscal",
  "document_type": "acordaos",
  "sources": ["tcu_acordaos"],
  "filters": {
    "year_from": 2020,
    "year_to": 2024
  },
  "hybrid_weights": {
    "bm25": 1.0,
    "vector": 1.2
  },
  "limit": 10,
  "offset": 0
}
```

**Resposta:**
```json
{
  "results": [
    {
      "document_id": "TCU-4567/2024",
      "title": "Acórdão 4567/2024",
      "content_preview": "...",
      "source_id": "tcu_acordaos",
      "rrf_score": 0.0852,
      "bm25_score": 15.34,
      "vector_score": 0.89,
      "rank_bm25": 1,
      "rank_vector": 3,
      "match_sources": ["bm25", "vector"],
      "metadata": {...}
    }
  ],
  "total": 42,
  "took_ms": 245.5,
  "rrf_k": 60,
  "weights": {"bm25": 1.0, "vector": 1.2}
}
```

## Resources

### document://{document_id}

Recupera um documento completo pelo ID.

**Exemplo:** `document://TCU-4567/2024`

### document://{document_id}/chunks

Recupera todos os chunks processados de um documento.

**Exemplo:** `document://TCU-4567/2024/chunks`

### chunk://{document_id}/{chunk_index}

Recupera um chunk específico.

**Exemplo:** `chunk://TCU-4567/2024/0`

### source://{source_id}/stats

Estatísticas de uma fonte de dados.

**Exemplo:** `source://tcu_acordaos/stats`

### source://list

Lista todas as fontes disponíveis.

### search://health

Health check dos índices de busca.

## Autenticação

O servidor suporta autenticação JWT via Keycloak TCU:

```bash
# Token JWT no header Authorization
Authorization: Bearer <jwt_token>
```

### Permissões

| Tool | Permissão Requerida |
|------|-------------------|
| search_exact | search:read |
| search_semantic | search:read |
| search_hybrid | search:read |
| get_document_details | document:read |

## Rate Limiting

Rate limiting por usuário via Redis:

| Tool | Limite |
|------|--------|
| search_exact | 60/min |
| search_semantic | 30/min |
| search_hybrid | 30/min |
| get_document_details | 100/min |

## Deploy

### Docker Compose

```bash
# Adicionar ao stack
docker-compose -f docker-compose.yml -f docker/docker-compose.mcp-hybrid.yml up -d

# Ou usar override
docker-compose up -d mcp-hybrid
```

### Kubernetes

```bash
# Aplicar manifests
kubectl apply -f k8s/mcp-hybrid-deployment.yaml

# Verificar deployment
kubectl get pods -n gabi -l app.kubernetes.io/component=mcp-hybrid
```

## Configuração

### Variáveis de Ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `GABI_MCP_ENABLED` | Habilitar MCP | `true` |
| `GABI_MCP_PORT` | Porta do servidor | `8001` |
| `GABI_MCP_AUTH_REQUIRED` | Requerer autenticação | `true` |
| `GABI_MCP_CORS_ORIGINS` | Origens CORS permitidas | `http://localhost:3000` |
| `GABI_SEARCH_RRF_K` | Constante RRF | `60` |
| `GABI_SEARCH_BM25_WEIGHT` | Peso BM25 | `1.0` |
| `GABI_SEARCH_VECTOR_WEIGHT` | Peso vetorial | `1.0` |

## Exemplos de Uso

### Inicializar conexão

```bash
# Conectar ao SSE endpoint
curl -N \
  -H "Authorization: Bearer <token>" \
  http://localhost:8001/mcp/sse
```

### Listar tools

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  "http://localhost:8001/mcp/message?sessionId=<session_id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/list",
    "params": {}
  }'
```

### Executar busca híbrida

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  "http://localhost:8001/mcp/message?sessionId=<session_id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "tools/call",
    "params": {
      "name": "search_hybrid",
      "arguments": {
        "query": "licitação pregão eletrônico",
        "document_type": "acordaos",
        "limit": 5
      }
    }
  }'
```

### Ler recurso

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8001/mcp/resources/document://TCU-4567/2024"
```

## Monitoramento

### Métricas

O servidor expõe métricas básicas no endpoint `/health`:

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
# Ver logs
docker logs -f gabi-mcp-hybrid

# Ou via kubectl
kubectl logs -f deployment/mcp-hybrid -n gabi
```

## Migração do MCP Legacy

```bash
# Verificar estado atual
python scripts/migrate_mcp_to_hybrid.py --check-only

# Executar migração
python scripts/migrate_mcp_to_hybrid.py --migrate

# Rollback (se necessário)
python scripts/migrate_mcp_to_hybrid.py --rollback
```

## Referência

- [MCP Specification](https://modelcontextprotocol.io/spec)
- [GABI Architecture](../vision.md)
- [Search Service](../src/gabi/services/search_service.py)
