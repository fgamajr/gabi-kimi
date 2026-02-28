using System.ComponentModel;
using System.Text.Json;
using ModelContextProtocol.Server;

namespace Gabi.Mcp;

[McpServerToolType]
public sealed class GabiMcpTools
{
    private readonly GabiApiClient _api;

    public GabiMcpTools(GabiApiClient api) => _api = api;

    [McpServerTool, Description("Search documents using hybrid search (BM25 + vector + graph). Returns matching documents with title, snippet, and score.")]
    public async Task<string> SearchDocuments(
        [Description("Search query text")] string query,
        [Description("Optional source ID to filter by (e.g. dou_dados_abertos_mensal)")] string? sourceId = null,
        [Description("Maximum number of results (1-100)")] int limit = 10,
        CancellationToken cancellationToken = default)
    {
        var q = Uri.EscapeDataString(query);
        var path = $"api/v1/search?q={q}&page=1&pageSize={limit}";
        if (!string.IsNullOrWhiteSpace(sourceId))
            path += "&sourceId=" + Uri.EscapeDataString(sourceId);
        var json = await _api.GetAsync(path, cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }

    [McpServerTool, Description("Get a single document by ID with full content and metadata.")]
    public async Task<string> GetDocument(
        [Description("Document GUID")] string documentId,
        CancellationToken cancellationToken = default)
    {
        var path = $"api/v1/documents/{documentId}";
        var json = await _api.GetAsync(path, cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }

    [McpServerTool, Description("Get related documents (citations, references) from the knowledge graph for a document.")]
    public async Task<string> GetRelatedDocuments(
        [Description("Document GUID")] string documentId,
        [Description("Maximum number of relations to return")] int limit = 20,
        CancellationToken cancellationToken = default)
    {
        var path = $"api/v1/documents/{documentId}/related?limit={limit}";
        var json = await _api.GetAsync(path, cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }

    [McpServerTool, Description("Search the knowledge graph by legal reference pattern (e.g. Acórdão, Lei, Súmula).")]
    public async Task<string> SearchLegalReferences(
        [Description("Reference pattern to search (e.g. Acórdão 123/2024, Lei 14.133)")] string reference,
        [Description("Maximum number of results")] int topK = 10,
        CancellationToken cancellationToken = default)
    {
        var path = $"api/v1/graph/search?ref={Uri.EscapeDataString(reference)}&topK={topK}";
        var json = await _api.GetAsync(path, cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }

    [McpServerTool, Description("List all configured data sources and their status.")]
    public async Task<string> ListSources(CancellationToken cancellationToken = default)
    {
        var json = await _api.GetAsync("api/v1/sources", cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }

    [McpServerTool, Description("Get pipeline statistics (job counts, document counts, health).")]
    public async Task<string> GetPipelineStatus(CancellationToken cancellationToken = default)
    {
        var json = await _api.GetAsync("api/v1/dashboard/pipeline/phases", cancellationToken);
        return JsonSerializer.Serialize(JsonSerializer.Deserialize<JsonElement>(json), new JsonSerializerOptions { WriteIndented = true });
    }
}
