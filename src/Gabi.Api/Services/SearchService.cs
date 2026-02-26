// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Diagnostics;
using Elastic.Clients.Elasticsearch;
using Gabi.Contracts.Api;
using Gabi.Contracts.Embed;
using Microsoft.Extensions.Logging;

namespace Gabi.Api.Services;

/// <summary>
/// Busca híbrida (BM25 + kNN) com fusão RRF. Requer Elasticsearch e IEmbedder configurados.
/// </summary>
public interface ISearchService
{
    /// <summary>
    /// Executa busca híbrida e retorna resultados paginados com latência.
    /// </summary>
    Task<SearchResultDto?> SearchAsync(
        string queryText,
        string? sourceId,
        int page,
        int pageSize,
        CancellationToken ct = default);
}

/// <summary>
/// Implementação: multi_match (BM25) + kNN (vetor) e fusão RRF em memória.
/// CODEX-E: SearchService implementa busca híbrida para GET /api/v1/search.
/// </summary>
public sealed class SearchService : ISearchService
{
    private const string DefaultIndexName = "gabi-docs";
    private const int RrfK = 60;
    private const int RankWindowSize = 200;

    private readonly ElasticsearchClient _client;
    private readonly IEmbedder _embedder;
    private readonly string _indexName;
    private readonly ILogger<SearchService> _logger;

    public SearchService(
        ElasticsearchClient client,
        IEmbedder embedder,
        ILogger<SearchService> logger,
        string? indexName = null)
    {
        _client = client;
        _embedder = embedder;
        _logger = logger;
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

        float[]? queryVector = null;
        try
        {
            var embedding = await _embedder.EmbedAsync(queryText.Trim(), ct);
            if (embedding.Count > 0)
                queryVector = embedding.ToArray();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Embedding failed for search query");
        }

        var bm25Task = RunBm25SearchAsync(queryText.Trim(), sourceId, RankWindowSize, ct);
        var knnTask = queryVector != null
            ? RunKnnSearchAsync(queryVector, sourceId, RankWindowSize, ct)
            : Task.FromResult<IReadOnlyList<EsSearchHit>>(Array.Empty<EsSearchHit>());

        await Task.WhenAll(bm25Task, knnTask).ConfigureAwait(false);

        var bm25Hits = await bm25Task.ConfigureAwait(false);
        var knnHits = await knnTask.ConfigureAwait(false);

        var merged = MergeRrf(bm25Hits, knnHits, RrfK);
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
                    : (h.ContentPreview.Length <= 240 ? h.ContentPreview : h.ContentPreview[..240])
            ))
            .ToList();

        stopwatch.Stop();
        var latencyMs = stopwatch.Elapsed.TotalMilliseconds;
        _logger.LogDebug("Search completed in {LatencyMs:F0}ms, total {Total} hits", latencyMs, total);

        return new SearchResultDto(
            Query: queryText.Trim(),
            Total: total,
            Page: safePage,
            PageSize: safePageSize,
            Hits: hits,
            LatencyMs: Math.Round(latencyMs, 2)
        );
    }

    private async Task<IReadOnlyList<EsSearchHit>> RunBm25SearchAsync(
        string queryText,
        string? sourceId,
        int size,
        CancellationToken ct)
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
            .SourceIncludes(new Field[] { "documentId", "sourceId", "title", "contentPreview", "ingestedAt" }),
            ct).ConfigureAwait(false);

        if (!response.IsValidResponse)
        {
            _logger.LogWarning("BM25 search failed: {Debug}", response.DebugInformation);
            return Array.Empty<EsSearchHit>();
        }

        return response.Hits
            .Where(h => h.Source != null)
            .Select((h, i) =>
            {
                var src = h.Source!;
                return new EsSearchHit
                {
                    DocumentId = src.DocumentId ?? h.Id,
                    SourceId = src.SourceId ?? string.Empty,
                    Title = src.Title,
                    ContentPreview = src.ContentPreview,
                    IngestedAt = src.IngestedAt
                };
            })
            .ToList();
    }

    private async Task<IReadOnlyList<EsSearchHit>> RunKnnSearchAsync(
        float[] queryVector,
        string? sourceId,
        int k,
        CancellationToken ct)
    {
        var numCandidates = Math.Min(500, k * 2);
        var response = await _client.SearchAsync<EsSearchHit>(s => s
            .Index(_indexName)
            .Size(k)
            .Knn(knn =>
            {
                knn.Field("embedding").QueryVector(queryVector).NumCandidates(numCandidates);
                if (string.IsNullOrWhiteSpace(sourceId))
                    knn.Filter(f => f.Term(t => t.Field("status").Value("active")));
                else
                    knn.Filter(f => f.Bool(bf => bf
                        .Must(m => m.Term(t => t.Field("status").Value("active")))
                        .Must(m => m.Term(t => t.Field("sourceId").Value(sourceId)))));
            })
            .SourceIncludes(new Field[] { "documentId", "sourceId", "title", "contentPreview", "ingestedAt" }),
            ct).ConfigureAwait(false);

        if (!response.IsValidResponse)
        {
            _logger.LogWarning("kNN search failed: {Debug}", response.DebugInformation);
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
                    IngestedAt = src.IngestedAt
                };
            })
            .ToList();
    }

    private static IReadOnlyList<EsSearchHit> MergeRrf(
        IReadOnlyList<EsSearchHit> bm25Hits,
        IReadOnlyList<EsSearchHit> knnHits,
        int rrfK)
    {
        var docToRrf = new Dictionary<string, double>(StringComparer.Ordinal);
        for (var i = 0; i < bm25Hits.Count; i++)
        {
            var id = bm25Hits[i].DocumentId;
            if (string.IsNullOrEmpty(id)) continue;
            var rank = i + 1;
            docToRrf.TryGetValue(id, out var score);
            docToRrf[id] = score + 1.0 / (rrfK + rank);
        }
        for (var i = 0; i < knnHits.Count; i++)
        {
            var id = knnHits[i].DocumentId;
            if (string.IsNullOrEmpty(id)) continue;
            var rank = i + 1;
            docToRrf.TryGetValue(id, out var score);
            docToRrf[id] = score + 1.0 / (rrfK + rank);
        }

        var byId = bm25Hits.Concat(knnHits)
            .GroupBy(h => h.DocumentId)
            .ToDictionary(g => g.Key!, g => g.First(), StringComparer.Ordinal);

        return docToRrf
            .OrderByDescending(x => x.Value)
            .Select(x => byId.TryGetValue(x.Key, out var hit) ? hit : null)
            .Where(h => h != null)
            .Cast<EsSearchHit>()
            .ToList();
    }

    private class EsSearchHit
    {
        public string DocumentId { get; set; } = string.Empty;
        public string SourceId { get; set; } = string.Empty;
        public string? Title { get; set; }
        public string? ContentPreview { get; set; }
        public DateTime? IngestedAt { get; set; }
    }
}
