# MCP (Model Context Protocol) - Especificação

## Visão Geral

O MCP expõe o sistema GabiSync como ferramenta cognitiva para modelos de IA.

> **Princípio:** MCP é **read-only**. Nunca altera dados no PostgreSQL.

---

## Ferramentas Disponíveis

### 1. list_sources

Lista todas as fontes de dados configuradas.

```csharp
[Tool("list_sources")]
public async Task<ListSourcesResult> ListSourcesAsync(
    [Parameter("include_disabled")] bool includeDisabled = false)
{
    var sources = await _db.Sources
        .Where(s => includeDisabled || s.Status == SourceStatus.Active)
        .Select(s => new SourceInfo
        {
            Id = s.Id,
            Name = s.Name,
            Description = s.Description,
            DocumentCount = s.Documents.Count,
            LastSyncAt = s.LastSyncAt
        })
        .ToListAsync();
    
    return new ListSourcesResult { Sources = sources };
}
```

**Uso:**
```json
{
  "tool": "list_sources",
  "parameters": {
    "include_disabled": false
  }
}
```

---

### 2. search

Busca documentos usando busca híbrida (BM25 + vetorial).

```csharp
[Tool("search")]
public async Task<SearchResult> SearchAsync(
    [Parameter("query", required: true)] string query,
    [Parameter("search_type")] string searchType = "hybrid",
    [Parameter("limit")] int limit = 10,
    [Parameter("filters")] SearchFilters? filters = null)
{
    var results = await _searchService.SearchAsync(
        query, 
        Enum.Parse<SearchType>(searchType),
        limit,
        filters);
    
    return new SearchResult { Results = results };
}
```

**Uso:**
```json
{
  "tool": "search",
  "parameters": {
    "query": "cooperativas em licitações",
    "search_type": "hybrid",
    "limit": 5,
    "filters": {
      "source_id": "tcu_sumulas",
      "year_from": 2020
    }
  }
}
```

---

### 3. get_document

Obtém um documento completo pelo ID.

```csharp
[Tool("get_document")]
public async Task<DocumentResult?> GetDocumentAsync(
    [Parameter("document_id", required: true)] string documentId)
{
    var doc = await _db.Documents
        .AsNoTracking()
        .Include(d => d.Chunks)
        .FirstOrDefaultAsync(d => d.DocumentId == documentId);
    
    if (doc == null || doc.IsDeleted)
        return null;
    
    return new DocumentResult
    {
        Id = doc.DocumentId,
        Title = doc.Title,
        Content = doc.Content,
        Metadata = doc.Metadata,
        Chunks = doc.Chunks.Select(c => new ChunkInfo
        {
            Index = c.ChunkIndex,
            Text = c.ChunkText,
            SectionType = c.SectionType
        }).ToList()
    };
}
```

**Uso:**
```json
{
  "tool": "get_document",
  "parameters": {
    "document_id": "SUMULA-274/2012"
  }
}
```

---

### 4. get_source_stats

Obtém estatísticas de uma fonte.

```csharp
[Tool("get_source_stats")]
public async Task<SourceStats?> GetSourceStatsAsync(
    [Parameter("source_id", required: true)] string sourceId)
{
    var source = await _db.Sources
        .AsNoTracking()
        .FirstOrDefaultAsync(s => s.Id == sourceId);
    
    if (source == null)
        return null;
    
    var stats = await _db.Documents
        .Where(d => d.SourceId == sourceId && !d.IsDeleted)
        .GroupBy(d => 1)
        .Select(g => new SourceStats
        {
            SourceId = sourceId,
            TotalDocuments = g.Count(),
            ActiveDocuments = g.Count(d => d.Status == DocumentStatus.Active),
            LastIngestedAt = g.Max(d => d.IngestedAt),
            DocumentsByYear = g.GroupBy(d => d.Metadata.Year)
                .Select(y => new { Year = y.Key, Count = y.Count() })
                .ToList()
        })
        .FirstOrDefaultAsync();
    
    return stats;
}
```

**Uso:**
```json
{
  "tool": "get_source_stats",
  "parameters": {
    "source_id": "tcu_sumulas"
  }
}
```

---

## Garantias de Segurança

### 1. Read-Only

```csharp
public class McpServer
{
    // ✅ Apenas queries, nunca comandos
    private readonly IQueryable<Document> _documents;
    
    public McpServer(IQueryable<Document> documents)
    {
        _documents = documents;
    }
    
    // ❌ NUNCA implementar:
    // - CreateDocument
    // - UpdateDocument
    // - DeleteDocument
    // - TriggerSync
}
```

### 2. Acesso a Stores Derivados

| Store | Acesso | Motivo |
|-------|--------|--------|
| PostgreSQL | ✅ Read | Dados canônicos |
| Elasticsearch | ✅ Read | Busca otimizada |
| pgvector | ✅ Read | Busca vetorial |
| PostgreSQL | ❌ Write | Proteger integridade |

### 3. Rate Limiting

```csharp
[Tool("search")]
[RateLimit(requestsPerMinute: 60)]
public async Task<SearchResult> SearchAsync(...)
```

---

## Configuração

### appsettings.json

```json
{
  "Mcp": {
    "Enabled": true,
    "Transport": "stdio",  // stdio | sse | http
    "RateLimit": {
      "RequestsPerMinute": 60,
      "BurstSize": 10
    },
    "AllowedOrigins": [
      "claude://localhost",
      "cursor://localhost"
    ]
  }
}
```

### Docker Compose

```yaml
services:
  mcp-server:
    build:
      context: .
      dockerfile: src/Gabi.Mcp/Dockerfile
    environment:
      - MCP_TRANSPORT=stdio
      - MCP_RATE_LIMIT_RPM=60
    depends_on:
      - postgres
      - elasticsearch
    read_only: true  # Filesystem read-only
```

---

## Exemplo de Uso

### Com Claude Desktop

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "gabi": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "gabi-mcp:latest"
      ]
    }
  }
}
```

### Fluxo de Interação

```
Usuário: "Quais súmulas do TCU falam sobre cooperativas?"

Claude ──▶ MCP:list_sources ──▶ Retorna: [tcu_sumulas, tcu_acordaos, ...]

Claude ──▶ MCP:search ──▶ query="cooperativas", source_id="tcu_sumulas"
         
         ◀── Retorna: [
               {id: "SUMULA-274/2012", snippet: "É vedada a participação..."},
               {id: "SUMULA-390/2015", snippet: "As cooperativas devem..."}
             ]

Claude ──▶ MCP:get_document ──▶ document_id="SUMULA-274/2012"

         ◀── Retorna: Documento completo com texto, metadados, etc.

Claude: "Encontrei a Súmula 274/2012 que trata especificamente 
         sobre a participação de cooperativas em licitações..."
```

---

## Testes

```csharp
[Fact]
public async Task Search_ReturnsResults()
{
    // Arrange
    var mcp = new McpServer(_searchService);
    
    // Act
    var result = await mcp.SearchAsync(
        query: "cooperativas",
        searchType: "hybrid",
        limit: 5);
    
    // Assert
    Assert.NotEmpty(result.Results);
    Assert.All(result.Results, r => 
        Assert.Contains("cooperativa", r.Snippet, StringComparison.OrdinalIgnoreCase));
}
```
