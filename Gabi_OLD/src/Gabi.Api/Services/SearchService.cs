// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Diagnostics;
using Elastic.Clients.Elasticsearch;
using Gabi.Contracts.Api;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Graph;
using Microsoft.Extensions.Logging;

namespace Gabi.Api.Services;

/// <summary>
/// Busca híbrida 3-strategy (BM25 + Vector + Graph) com fusão RRF.
/// BM25 from ES, Vector from pgvector, Graph from PG adjacency table.
/// </summary>
public interface ISearchService
{
    Task<SearchResultDto?> SearchAsync(
        string queryText,
        string? sourceId,
        int page,
        int pageSize,
        CancellationToken ct = default);
}

public sealed class SearchService : ISearchService
{
    private const string DefaultIndexName = "gabi-docs";
    private const int RrfK = 60;
    private const int RankWindowSize = 200;

    private readonly ElasticsearchClient _client;
    private readonly IEmbedder _embedder;
    private readonly IDocumentEmbeddingRepository? _embeddingRepo;
    private readonly IDocumentRelationshipRepository? _relationshipRepo;
    private readonly string _indexName;
    private readonly ILogger<SearchService> _logger;

    public SearchService(
        ElasticsearchClient client,
        IEmbedder embedder,
        ILogger<SearchService> logger,
        IDocumentEmbeddingRepository? embeddingRepo = null,
        IDocumentRelationshipRepository? relationshipRepo = null,
        string? indexName = null)
    {
        _client = client;
        _embedder = embedder;
        _logger = logger;
        _embeddingRepo = embeddingRepo;
        _relationshipRepo = relationshipRepo;
        _indexName = string.IsNullOrWhiteSpace(indexName) ? DefaultIndexName : indexName.Trim();
    }

    public async Task<SearchResultDto?> SearchAsync(
        string queryText,
        string? sourceId,
        int page,
        int pageSize,
        CancellationToken ct = default)
    {
        var stopwatch = Stopwatch.StartNew();
        ct.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(queryText))
            return null;

        var safePage = page > 0 ? page : 1;
        var safePageSize = Math.Clamp(pageSize > 0 ? pageSize : 20, 1, 100);

        // Strategy 1: BM25 from Elasticsearch (runs concurrently — uses ES client, not PG)
        var bm25Task = RunBm25SearchAsync(queryText.Trim(), sourceId, RankWindowSize, ct);

        // Strategy 2: Vector search from pgvector
        // Strategy 3: Graph search from PG adjacency
        // NOTE: vector + graph run sequentially to avoid concurrent use of the same
        // NpgsqlConnection from EF Core DbContext (Dapper shares the connection).
        float[]? queryVector = null;
        bool embeddingFailed = false;
        try
        {
            var embedding = await _embedder.EmbedAsync(queryText.Trim(), ct);
            if (embedding.Count > 0)
                queryVector = embedding.ToArray();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Embedding failed for search query");
            embeddingFailed = true;
        }

        IReadOnlyList<VectorSearchResult> vectorHits;
        if (queryVector != null && _embeddingRepo != null)
            vectorHits = await _embeddingRepo.SearchSimilarAsync(queryVector, RankWindowSize, sourceId, ct);
        else
            vectorHits = Array.Empty<VectorSearchResult>();

        IReadOnlyList<GraphSearchResult> graphHits;
        if (_relationshipRepo != null)
            graphHits = await _relationshipRepo.SearchByRefAsync(queryText.Trim(), RankWindowSize, ct);
        else
            graphHits = Array.Empty<GraphSearchResult>();

        var bm25Hits = await bm25Task.ConfigureAwait(false);

        // RRF fusion across all strategies
        var merged = MergeRrf(bm25Hits, vectorHits, graphHits, RrfK);
        var total = merged.Count;
        var hits = merged
            .Skip((safePage - 1) * safePageSize)
            .Take(safePageSize)
            .Select(h => new SearchHitDto(
                Id: h.DocumentId,
                SourceId: h.SourceId,
                ExternalId: h.DocumentId,
                Title: h.Title,
                UpdatedAt: h.IngestedAt,
                Snippet: string.IsNullOrWhiteSpace(h.ContentPreview)
                    ? string.Empty
                    : (h.ContentPreview.Length <= 240 ? h.ContentPreview : h.ContentPreview[..240]),
                SourceViewUrl: ReadMetadataUrl(h.Metadata, "source_view_url", "view_url", "url"),
                SourceDownloadUrl: ReadMetadataUrl(h.Metadata, "source_download_url", "download_url", "url"),
                SourcePdfUrl: ReadMetadataUrl(h.Metadata, "source_pdf_url", "pdf_url", "source_download_url"),
                SourceAccessibleUrl: $"/api/v1/documents/{h.DocumentId}/source-file",
                Section: ReadMetadataValue(h.Metadata, "secao", "section"),
                PublicationDate: ReadMetadataValue(h.Metadata, "data_publicacao", "publication_date"),
                PageStart: ReadMetadataValue(h.Metadata, "page_start", "pagina"),
                PageEnd: ReadMetadataValue(h.Metadata, "page_end", "pagina")
            ))
            .ToList();

        stopwatch.Stop();
        var latencyMs = stopwatch.Elapsed.TotalMilliseconds;
        _logger.LogDebug(
            "Search completed in {LatencyMs:F0}ms: bm25={Bm25}, vector={Vector}, graph={Graph}, total={Total}",
            latencyMs, bm25Hits.Count, vectorHits.Count, graphHits.Count, total);

        return new SearchResultDto(
            Query: queryText.Trim(),
            Total: total,
            Page: safePage,
            PageSize: safePageSize,
            Hits: hits,
            LatencyMs: Math.Round(latencyMs, 2),
            EmbeddingFailed: embeddingFailed
        );
    }

    private async Task<IReadOnlyList<EsSearchHit>> RunBm25SearchAsync(
        string queryText, string? sourceId, int size, CancellationToken ct)
    {
        var response = await _client.SearchAsync<EsSearchHit>(s => s
            .Index(_indexName)
            .Size(size)
            .Query(q => q.Bool(b =>
            {
                b.Must(m => m.MultiMatch(mm => mm
                    .Query(queryText)
                    .Fields(new[] { "title^3", "contentPreview^2" })
                    .Analyzer("portuguese")));
                if (string.IsNullOrWhiteSpace(sourceId))
                    b.Filter(f => f.Term(t => t.Field("status").Value("active")));
                else
                    b.Filter(f => f.Bool(bf => bf
                        .Must(m => m.Term(t => t.Field("status").Value("active")))
                        .Must(m => m.Term(t => t.Field("sourceId").Value(sourceId)))));
            }))
            .SourceIncludes(new Field[] { "documentId", "sourceId", "title", "contentPreview", "ingestedAt", "metadata" }),
            ct).ConfigureAwait(false);

        if (!response.IsValidResponse)
        {
            _logger.LogWarning("BM25 search failed: {Debug}", response.DebugInformation);
            return Array.Empty<EsSearchHit>();
        }

        return response.Hits
            .Where(h => h.Source != null)
            .Select(h =>
            {
                var src = h.Source!;
                return new EsSearchHit
                {
                    DocumentId = src.DocumentId ?? h.Id,
                    SourceId = src.SourceId ?? string.Empty,
                    Title = src.Title,
                    ContentPreview = src.ContentPreview,
                    IngestedAt = src.IngestedAt,
                    Metadata = src.Metadata
                };
            })
            .ToList();
    }

    private static IReadOnlyList<EsSearchHit> MergeRrf(
        IReadOnlyList<EsSearchHit> bm25Hits,
        IReadOnlyList<VectorSearchResult> vectorHits,
        IReadOnlyList<GraphSearchResult> graphHits,
        int rrfK)
    {
        var docToRrf = new Dictionary<string, double>(StringComparer.Ordinal);

        // BM25 scores
        for (var i = 0; i < bm25Hits.Count; i++)
        {
            var id = bm25Hits[i].DocumentId;
            if (string.IsNullOrEmpty(id)) continue;
            docToRrf.TryGetValue(id, out var score);
            docToRrf[id] = score + 1.0 / (rrfK + i + 1);
        }

        // Vector scores (deduplicate by documentId — multiple chunks may match)
        var seenVectorDocs = new Dictionary<string, int>(StringComparer.Ordinal);
        for (var i = 0; i < vectorHits.Count; i++)
        {
            var id = vectorHits[i].DocumentId.ToString();
            if (!seenVectorDocs.TryAdd(id, i)) continue; // first occurrence gets best rank
            docToRrf.TryGetValue(id, out var score);
            docToRrf[id] = score + 1.0 / (rrfK + seenVectorDocs.Count);
        }

        // Graph scores (boost source documents that match references)
        var seenGraphDocs = new Dictionary<string, int>(StringComparer.Ordinal);
        for (var i = 0; i < graphHits.Count; i++)
        {
            var id = graphHits[i].SourceDocumentId.ToString();
            if (!seenGraphDocs.TryAdd(id, i)) continue;
            docToRrf.TryGetValue(id, out var score);
            docToRrf[id] = score + 1.0 / (rrfK + seenGraphDocs.Count);
        }

        // Collect full hit data (prefer BM25 hit data since it has all fields)
        var byId = bm25Hits
            .Where(h => !string.IsNullOrEmpty(h.DocumentId))
            .GroupBy(h => h.DocumentId!)
            .ToDictionary(g => g.Key, g => g.First(), StringComparer.Ordinal);

        return docToRrf
            .OrderByDescending(x => x.Value)
            .Select(x =>
            {
                if (byId.TryGetValue(x.Key, out var hit)) return hit;
                // Create minimal hit for vector/graph-only results
                return new EsSearchHit { DocumentId = x.Key };
            })
            .ToList();
    }

    private static string? ReadMetadataUrl(IReadOnlyDictionary<string, object>? metadata, params string[] keys)
        => ReadMetadataValue(metadata, keys);

    private static string? ReadMetadataValue(IReadOnlyDictionary<string, object>? metadata, params string[] keys)
    {
        if (metadata == null || keys.Length == 0) return null;
        foreach (var key in keys)
        {
            if (metadata.TryGetValue(key, out var value) && value != null)
            {
                var text = value.ToString();
                if (!string.IsNullOrWhiteSpace(text)) return text;
            }
        }
        return null;
    }

    private class EsSearchHit
    {
        public string DocumentId { get; set; } = string.Empty;
        public string SourceId { get; set; } = string.Empty;
        public string? Title { get; set; }
        public string? ContentPreview { get; set; }
        public DateTime? IngestedAt { get; set; }
        public IReadOnlyDictionary<string, object>? Metadata { get; set; }
    }
}
