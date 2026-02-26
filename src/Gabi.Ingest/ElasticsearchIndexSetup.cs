using Elastic.Clients.Elasticsearch;
using Microsoft.Extensions.Logging;

namespace Gabi.Ingest;

/// <summary>
/// Cria o índice de documentos com mapping para busca híbrida (BM25 + kNN).
/// Idempotente: não falha se o índice já existir.
/// </summary>
public sealed class ElasticsearchIndexSetup
{
    public const string DefaultIndexName = "gabi-docs";
    private const int EmbeddingDimensions = 384;

    private readonly ElasticsearchClient _client;
    private readonly string _indexName;
    private readonly ILogger<ElasticsearchIndexSetup> _logger;

    public ElasticsearchIndexSetup(
        ElasticsearchClient client,
        ILogger<ElasticsearchIndexSetup> logger,
        string? indexName = null)
    {
        _client = client;
        _logger = logger;
        _indexName = string.IsNullOrWhiteSpace(indexName) ? DefaultIndexName : indexName.Trim();
    }

    /// <summary>
    /// Garante que o índice existe com o mapping correto (dense_vector 384 + text para BM25).
    /// Se o índice já existir, não altera o mapping (idempotente).
    /// </summary>
    public async Task EnsureIndexExistsAsync(CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            var existsResponse = await _client.Indices.ExistsAsync(_indexName, ct);

            if (existsResponse.Exists)
            {
                _logger.LogDebug("Index {IndexName} already exists, skipping creation", _indexName);
                return;
            }

            var createResponse = await _client.Indices.CreateAsync<EsDocumentMapping>(
                c => c.Index(_indexName).Mappings(m => m.Properties(p => p
                    .Keyword(k => k.DocumentId)
                    .Keyword(k => k.SourceId)
                    .Text(t => t.Title, td => td.Analyzer("portuguese"))
                    .Text(t => t.ContentPreview, td => td.Analyzer("portuguese"))
                    .Keyword(k => k.Fingerprint)
                    .Keyword(k => k.Status)
                    .Date(d => d.IngestedAt)
                    .DenseVector(dv => dv.Embedding!, d => d.Dims(EmbeddingDimensions).Index(true)))),
                ct);

            if (!createResponse.IsValidResponse)
            {
                var err = createResponse.ElasticsearchServerError?.Error?.Reason ?? createResponse.DebugInformation ?? "Unknown";
                _logger.LogWarning("Failed to create index {IndexName}: {Error}", _indexName, err);
                throw new InvalidOperationException($"Elasticsearch index creation failed: {err}");
            }

            _logger.LogInformation("Created Elasticsearch index {IndexName} with hybrid search mapping", _indexName);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ElasticsearchIndexSetup failed for {IndexName}", _indexName);
            throw;
        }
    }

    /// <summary>
    /// Classe usada apenas para definição do mapping no CreateAsync.
    /// Nomes de propriedade em PascalCase são serializados como camelCase pelo client.
    /// </summary>
    private sealed class EsDocumentMapping
    {
        public string DocumentId { get; set; } = string.Empty;
        public string SourceId { get; set; } = string.Empty;
        public string Title { get; set; } = string.Empty;
        public string ContentPreview { get; set; } = string.Empty;
        public string Fingerprint { get; set; } = string.Empty;
        public string Status { get; set; } = "active";
        public DateTime IngestedAt { get; set; }
        public float[]? Embedding { get; set; }
        public IReadOnlyList<EsChunkMapping>? Chunks { get; set; }
        public Dictionary<string, object>? Metadata { get; set; }
    }

    private sealed class EsChunkMapping
    {
        public string ChunkId { get; set; } = string.Empty;
        public int ChunkIndex { get; set; }
        public string Text { get; set; } = string.Empty;
        public float[]? Embedding { get; set; }
    }
}
