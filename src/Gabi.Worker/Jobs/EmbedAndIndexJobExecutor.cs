using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Processes a batch of document IDs: load from Postgres, normalize -> chunk -> embed -> index, then mark completed.
/// Enqueued by IngestJobExecutor (fan-out). Queue: embed. Single-in-flight is NOT enforced per source.
/// </summary>
public class EmbedAndIndexJobExecutor : IJobExecutor
{
    public const int MaxBatchSize = 64;

    public string JobType => "embed_and_index";

    private readonly GabiDbContext _context;
    private readonly ILogger<EmbedAndIndexJobExecutor> _logger;
    private readonly ICanonicalDocumentNormalizer _normalizer;
    private readonly IChunker _chunker;
    private readonly IEmbedder _embedder;
    private readonly IDocumentIndexer _indexer;

    public EmbedAndIndexJobExecutor(
        GabiDbContext context,
        ICanonicalDocumentNormalizer normalizer,
        IChunker chunker,
        IEmbedder embedder,
        IDocumentIndexer indexer,
        ILogger<EmbedAndIndexJobExecutor> logger)
    {
        _context = context;
        _normalizer = normalizer;
        _chunker = chunker;
        _embedder = embedder;
        _indexer = indexer;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var documentIds = ParseDocumentIdsFromPayload(job.Payload);
        if (documentIds.Count == 0)
        {
            _logger.LogWarning("EmbedAndIndex job {JobId} has no valid document_ids", job.Id);
            return new JobResult { Status = JobTerminalStatus.Success };
        }

        var docs = await _context.Documents
            .Where(d => d.SourceId == sourceId && documentIds.Contains(d.Id) && d.Status == "pending")
            .ToListAsync(ct);

        if (docs.Count == 0)
        {
            _logger.LogInformation("EmbedAndIndex job {JobId}: no pending documents found for {Count} IDs", job.Id, documentIds.Count);
            return new JobResult { Status = JobTerminalStatus.Success };
        }

        var completed = 0;
        var failed = 0;
        var interruptedByPause = false;

        // Phase 1: normalize + chunk + embed (sequential; embedding is the bottleneck)
        // Collect successfully embedded docs for bulk indexing in Phase 2.
        var pendingIndex = new List<(DocumentEntity Doc, CanonicalTextDocument Canonical, IndexDocument IndexDoc, IReadOnlyList<IndexChunk> Chunks)>();

        foreach (var doc in docs)
        {
            if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
            {
                _logger.LogInformation("EmbedAndIndex interrupted for {SourceId}: source paused/stopped at {Completed} docs", sourceId, completed + failed);
                interruptedByPause = true;
                break;
            }

            try
            {
                var canonical = _normalizer.Normalize(new CanonicalTextDocument
                {
                    SourceId = doc.SourceId,
                    ExternalId = doc.ExternalId ?? doc.DocumentId ?? doc.Id.ToString(),
                    Title = doc.Title,
                    Content = doc.Content ?? string.Empty,
                    ContentType = "text/plain",
                    Language = "pt-BR",
                    Metadata = DeserializeMetadata(doc.Metadata)
                });

                if (string.IsNullOrWhiteSpace(canonical.Content))
                {
                    MarkDocumentMetadataOnly(doc);
                    completed++;
                    continue;
                }

                var (indexDoc, indexChunks) = await EmbedDocumentAsync(doc, canonical, ct);
                pendingIndex.Add((doc, canonical, indexDoc, indexChunks));
            }
            catch (Exception ex)
            {
                failed++;
                MarkDocumentFailed(doc, "embed_failed", ex.Message);
                _logger.LogWarning(ex, "EmbedAndIndex embed phase failed for document {DocId}", doc.Id);
            }
        }

        // Phase 2: bulk index all successfully embedded docs in a single HTTP round-trip
        if (pendingIndex.Count > 0)
        {
            var bulkBatch = pendingIndex
                .Select(p => (p.IndexDoc, p.Chunks))
                .ToList();
            var bulkResults = await _indexer.BulkIndexAsync(bulkBatch, ct);

            for (var i = 0; i < pendingIndex.Count && i < bulkResults.Count; i++)
            {
                var (doc, canonical, indexDoc, _) = pendingIndex[i];
                var result = bulkResults[i];

                if (result.Status is IndexingStatus.Failed or IndexingStatus.RolledBack)
                {
                    failed++;
                    var message = result.Errors.Count > 0
                        ? string.Join("; ", result.Errors)
                        : "Bulk indexing failed without explicit error";
                    MarkDocumentFailed(doc, "index_failed", message);
                    _logger.LogWarning("BulkIndex failed for document {DocId}: {Error}", doc.Id, message);
                    continue;
                }

                var enrichedCanonical = canonical with
                {
                    Metadata = EnrichMetadataForIngestV2(canonical.Metadata, result)
                };
                ApplyCanonicalToDocument(doc, enrichedCanonical, doc.LinkId, doc.FetchItemId, "ingest_v2", "ingested_v2");
                doc.ElasticsearchId = indexDoc.DocumentId;

                if (doc.FetchItemId.HasValue)
                {
                    var fetchItemId = doc.FetchItemId.Value;
                    var linkId = doc.LinkId;
                    var docId = doc.Id;
                    var now = DateTime.UtcNow;
                    await _context.Database.ExecuteSqlRawAsync(
                        """
                        UPDATE discovered_links
                        SET "IngestStatus" = 'completed', "UpdatedAt" = {0}
                        WHERE "Id" = {1}
                          AND NOT EXISTS (
                            SELECT 1 FROM documents d
                            WHERE d."FetchItemId" = {2} AND d."Id" <> {3}
                              AND (d."Status" IS NULL OR d."Status" <> 'completed')
                          )
                        """,
                        ct, now, linkId, fetchItemId, docId);
                }

                completed++;
            }
        }

        await _context.SaveChangesAsync(ct);

        progress.Report(new JobProgress
        {
            PercentComplete = 100,
            Message = $"EmbedAndIndex {completed + failed}/{docs.Count}",
            Metrics = new Dictionary<string, object>
            {
                ["documents_completed"] = completed,
                ["documents_failed"] = failed
            }
        });

        _logger.LogInformation(
            "EmbedAndIndex job {JobId} finished for {SourceId}: completed={Completed}, failed={Failed}",
            job.Id, sourceId, completed, failed);

        var metadata = new Dictionary<string, object>
        {
            ["documents_completed"] = completed,
            ["documents_failed"] = failed
        };
        if (interruptedByPause)
            metadata["interrupted_by"] = "pause";
        return new JobResult { Status = JobTerminalStatus.Success, Metadata = metadata };
    }

    /// <summary>Returns (IndexDocument, IndexChunks) after normalize→chunk→embed. Throws on failure.</summary>
    private async Task<(IndexDocument IndexDoc, IReadOnlyList<IndexChunk> Chunks)> EmbedDocumentAsync(
        DocumentEntity doc, CanonicalTextDocument canonical, CancellationToken ct)
    {
        var chunkMetadata = new Dictionary<string, object>(canonical.Metadata, StringComparer.OrdinalIgnoreCase)
        {
            ["source_id"] = canonical.SourceId,
            ["external_id"] = canonical.ExternalId
        };

        var chunkConfig = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 512, Overlap = 64 };
        var chunkResult = _chunker.Chunk(canonical.Content, chunkConfig, chunkMetadata);
        if (chunkResult.Chunks.Count == 0)
            throw new InvalidOperationException("Chunking returned zero chunks for non-empty content.");

        EmbeddingResult embeddings;
        try
        {
            embeddings = await _embedder.EmbedChunksAsync(chunkResult.Chunks, doc.Id.ToString(), ct);
        }
        catch (Exception ex) when (IsRateLimitException(ex))
        {
            throw new EmbeddingRateLimitException("Embedding API rate limit (429).", ex);
        }

        var indexDocument = BuildIndexDocument(doc, canonical, chunkResult.Chunks.Count);
        var indexChunks = BuildIndexChunks(embeddings);
        return (indexDocument, indexChunks);
    }

    private static List<Guid> ParseDocumentIdsFromPayload(IReadOnlyDictionary<string, object> payload)
    {
        if (payload == null || !payload.TryGetValue("document_ids", out var raw) || raw == null)
            return new List<Guid>();

        var list = new List<Guid>();
        if (raw is not List<object> arr)
            return list;

        foreach (var item in arr.Take(MaxBatchSize))
        {
            string? s = null;
            if (item is JsonElement je)
                s = je.GetString();
            else if (item is string s2)
                s = s2;
            if (!string.IsNullOrEmpty(s) && Guid.TryParse(s, out var g))
                list.Add(g);
        }

        return list;
    }

    private static IndexDocument BuildIndexDocument(DocumentEntity doc, CanonicalTextDocument canonical, int chunksCount)
    {
        return new IndexDocument
        {
            DocumentId = doc.Id.ToString(),
            SourceId = canonical.SourceId,
            Title = canonical.Title ?? string.Empty,
            ContentPreview = BuildContentPreview(canonical.Content),
            Fingerprint = ComputeSha256(canonical.Content),
            Metadata = canonical.Metadata,
            Status = "active",
            ChunksCount = chunksCount,
            IngestedAt = DateTime.UtcNow
        };
    }

    private static IReadOnlyList<IndexChunk> BuildIndexChunks(EmbeddingResult embeddingResult)
    {
        var chunks = new List<IndexChunk>(embeddingResult.Chunks.Count);
        foreach (var embeddedChunk in embeddingResult.Chunks)
        {
            chunks.Add(new IndexChunk
            {
                ChunkId = $"{embeddingResult.DocumentId}:chunk:{embeddedChunk.Index}",
                ChunkIndex = embeddedChunk.Index,
                Text = embeddedChunk.Text,
                Embedding = embeddedChunk.Embedding,
                Metadata = embeddedChunk.Metadata
            });
        }
        return chunks;
    }

    private static IReadOnlyDictionary<string, object> EnrichMetadataForIngestV2(
        IReadOnlyDictionary<string, object> existingMetadata,
        IndexingResult indexingResult)
    {
        var metadata = new Dictionary<string, object>(existingMetadata, StringComparer.OrdinalIgnoreCase)
        {
            ["ingest_version"] = "v2",
            ["ingest_index_status"] = indexingResult.Status.ToString().ToLowerInvariant(),
            ["ingest_index_chunks"] = indexingResult.ChunksIndexed,
            ["ingest_indexed_at"] = DateTime.UtcNow.ToString("O")
        };
        return metadata;
    }

    private static string BuildContentPreview(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return string.Empty;
        var trimmed = content.Trim();
        return trimmed.Length <= 240 ? trimmed : trimmed[..240];
    }

    private static void ApplyCanonicalToDocument(
        DocumentEntity doc,
        CanonicalTextDocument canonical,
        long linkId,
        long? fetchItemId,
        string updatedBy = "ingest_v1",
        string processingStage = "ingested")
    {
        doc.LinkId = linkId;
        doc.FetchItemId = fetchItemId;
        doc.SourceId = canonical.SourceId;
        doc.DocumentId = string.IsNullOrWhiteSpace(doc.DocumentId) ? canonical.ExternalId : doc.DocumentId;
        doc.ExternalId = canonical.ExternalId;
        doc.Title = canonical.Title;
        doc.Content = canonical.Content;
        doc.ContentHash = ComputeSha256(canonical.Content);
        doc.Metadata = SerializeMetadata(canonical.Metadata);
        doc.Status = "completed";
        doc.ProcessingStage = processingStage;
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = updatedBy;
    }

    private static void MarkDocumentFailed(DocumentEntity doc, string stage, string? errorMessage = null)
    {
        doc.Status = "failed";
        doc.ProcessingStage = stage;
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = "ingest_v2";

        var metadata = DeserializeMetadata(doc.Metadata);
        if (!string.IsNullOrWhiteSpace(errorMessage))
            metadata["ingest_error"] = errorMessage.Length > 500 ? errorMessage[..500] : errorMessage;
        doc.Metadata = SerializeMetadata(metadata);
    }

    private static void MarkDocumentMetadataOnly(DocumentEntity doc)
    {
        doc.Status = "completed";
        doc.ProcessingStage = "metadata_only";
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = "ingest_v2";

        var metadata = DeserializeMetadata(doc.Metadata);
        metadata["ingest_note"] = "empty_content_metadata_only";
        metadata["ingest_index_status"] = "skipped";
        doc.Metadata = SerializeMetadata(metadata);
    }

    private static Dictionary<string, object> DeserializeMetadata(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
            return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var data = JsonSerializer.Deserialize<Dictionary<string, object?>>(json);
            if (data == null)
                return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            var result = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in data)
            {
                if (item.Value != null)
                    result[item.Key] = item.Value;
            }
            return result;
        }
        catch
        {
            return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        }
    }

    private static string SerializeMetadata(IReadOnlyDictionary<string, object> metadata)
    {
        return metadata.Count == 0 ? "{}" : JsonSerializer.Serialize(metadata);
    }

    private static string ComputeSha256(string input)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static bool IsRateLimitException(Exception ex)
    {
        var message = (ex.Message + " " + (ex.InnerException?.Message ?? "")).ToLowerInvariant();
        return message.Contains("429") || message.Contains("too many requests") || message.Contains("rate limit");
    }
}
