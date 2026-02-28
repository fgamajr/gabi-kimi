using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Graph;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Fan-out job: processes documents through Chunk → then fans out to:
///   A) BM25 index (Elasticsearch, text only)
///   B) Embed → pgvector store
///   C) Extract relationships → KG adjacency table
/// Each output is independent and fault-tolerant.
/// </summary>
public class ChunkAndExtractJobExecutor : IJobExecutor
{
    public const int MaxBatchSize = 64;
    private const int MaxContentSizeBytes = 512 * 1024;

    public string JobType => "chunk_and_extract";

    private readonly GabiDbContext _context;
    private readonly ILogger<ChunkAndExtractJobExecutor> _logger;
    private readonly ICanonicalDocumentNormalizer _normalizer;
    private readonly IChunker _chunker;
    private readonly IEmbedder _embedder;
    private readonly IDocumentIndexer _indexer;
    private readonly IDocumentEmbeddingRepository _embeddingRepo;
    private readonly IDocumentRelationshipRepository _relationshipRepo;
    private readonly IDocumentRelationshipExtractor _relationshipExtractor;
    private readonly IConfiguration _configuration;

    public ChunkAndExtractJobExecutor(
        GabiDbContext context,
        ICanonicalDocumentNormalizer normalizer,
        IChunker chunker,
        IEmbedder embedder,
        IDocumentIndexer indexer,
        IDocumentEmbeddingRepository embeddingRepo,
        IDocumentRelationshipRepository relationshipRepo,
        IDocumentRelationshipExtractor relationshipExtractor,
        ILogger<ChunkAndExtractJobExecutor> logger,
        IConfiguration configuration)
    {
        _context = context;
        _normalizer = normalizer;
        _chunker = chunker;
        _embedder = embedder;
        _indexer = indexer;
        _embeddingRepo = embeddingRepo;
        _relationshipRepo = relationshipRepo;
        _relationshipExtractor = relationshipExtractor;
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var documentIds = ParseDocumentIdsFromPayload(job.Payload);
        if (documentIds.Count == 0)
        {
            _logger.LogWarning("ChunkAndExtract job {JobId} has no valid document_ids", job.Id);
            return new JobResult { Status = JobTerminalStatus.Success };
        }

        var enableBm25 = _configuration.GetValue<bool>("Pipeline:EnableBM25Index", true);
        var enableEmbeddings = _configuration.GetValue<bool>("Pipeline:EnableEmbeddings", true);
        var enableGraph = _configuration.GetValue<bool>("Pipeline:EnableGraphExtraction", true);

        var docs = await _context.Documents
            .Where(d => d.SourceId == sourceId && documentIds.Contains(d.Id) && d.Status == "pending")
            .ToListAsync(ct);

        if (docs.Count == 0)
        {
            _logger.LogInformation("ChunkAndExtract job {JobId}: no pending documents for {Count} IDs", job.Id, documentIds.Count);
            return new JobResult { Status = JobTerminalStatus.Success };
        }

        var completed = 0;
        var failed = 0;
        var bm25Ok = 0;
        var embedOk = 0;
        var graphOk = 0;

        foreach (var doc in docs)
        {
            if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
            {
                _logger.LogInformation("ChunkAndExtract interrupted: source {SourceId} paused/stopped", sourceId);
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

                var contentBytes = Encoding.UTF8.GetByteCount(canonical.Content);
                if (contentBytes > MaxContentSizeBytes)
                {
                    MarkDocumentFailed(doc, "content_too_large",
                        $"Content exceeds size limit ({contentBytes:N0} > {MaxContentSizeBytes:N0})");
                    failed++;
                    continue;
                }

                // Chunk (shared step)
                var chunkConfig = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 512, Overlap = 64 };
                var chunkMetadata = new Dictionary<string, object>(canonical.Metadata, StringComparer.OrdinalIgnoreCase)
                {
                    ["source_id"] = canonical.SourceId,
                    ["external_id"] = canonical.ExternalId
                };
                var chunkResult = _chunker.Chunk(canonical.Content, chunkConfig, chunkMetadata);

                // === Fan-out A: BM25 Index (ES, text only) ===
                if (enableBm25)
                {
                    try
                    {
                        var indexDoc = BuildIndexDocument(doc, canonical, chunkResult.Chunks.Count);
                        var indexChunks = chunkResult.Chunks.Select((c, i) => new IndexChunk
                        {
                            ChunkId = $"{doc.Id}:chunk:{i}",
                            ChunkIndex = i,
                            Text = c.Text,
                            Embedding = null, // BM25 only — no vectors in ES
                            Metadata = c.Metadata
                        }).ToList();
                        var result = await _indexer.IndexAsync(indexDoc, indexChunks, ct);
                        if (result.Status == IndexingStatus.Success)
                        {
                            doc.ElasticsearchId = indexDoc.DocumentId;
                            bm25Ok++;
                        }
                        else
                            _logger.LogWarning("BM25 index failed for {DocId}: {Errors}", doc.Id,
                                string.Join("; ", result.Errors));
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "BM25 index exception for {DocId}", doc.Id);
                    }
                }

                // === Fan-out B: Embed → pgvector ===
                if (enableEmbeddings && chunkResult.Chunks.Count > 0)
                {
                    try
                    {
                        var embedResult = await _embedder.EmbedChunksAsync(chunkResult.Chunks, doc.Id.ToString(), ct);
                        var chunkEmbeddings = embedResult.Chunks
                            .Where(c => c.Embedding is { Count: > 0 })
                            .Select(c => new ChunkEmbedding(c.Index, c.Text, c.Embedding!.ToArray(), embedResult.Model ?? "unknown"))
                            .ToList();
                        if (chunkEmbeddings.Count > 0)
                        {
                            await _embeddingRepo.UpsertChunkEmbeddingsAsync(doc.Id, doc.SourceId, chunkEmbeddings, ct);
                            embedOk++;
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Embedding failed for {DocId}", doc.Id);
                    }
                }

                // === Fan-out C: Extract relationships → KG ===
                if (enableGraph)
                {
                    try
                    {
                        var relations = _relationshipExtractor.Extract(canonical);
                        if (relations.Count > 0)
                        {
                            await _relationshipRepo.UpsertRelationshipsAsync(doc.Id, relations, ct);
                            graphOk++;
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Graph extraction failed for {DocId}", doc.Id);
                    }
                }

                // Mark completed
                ApplyCanonicalToDocument(doc, canonical, doc.LinkId, doc.FetchItemId);

                if (doc.FetchItemId.HasValue)
                {
                    var now = DateTime.UtcNow;
                    await _context.Database.ExecuteSqlInterpolatedAsync(
                        $"""
                        UPDATE discovered_links
                        SET "IngestStatus" = 'completed', "UpdatedAt" = {now}
                        WHERE "Id" = {doc.LinkId}
                          AND NOT EXISTS (
                            SELECT 1 FROM documents d
                            WHERE d."FetchItemId" = {doc.FetchItemId.Value} AND d."Id" <> {doc.Id}
                              AND (d."Status" IS NULL OR d."Status" <> 'completed')
                          )
                        """, ct);
                }

                completed++;
            }
            catch (Exception ex)
            {
                failed++;
                MarkDocumentFailed(doc, "chunk_and_extract_failed", ex.Message);
                _logger.LogWarning(ex, "ChunkAndExtract failed for document {DocId}", doc.Id);
            }
        }

        await _context.SaveChangesAsync(ct);

        progress.Report(new JobProgress
        {
            PercentComplete = 100,
            Message = $"ChunkAndExtract {completed + failed}/{docs.Count}",
            Metrics = new Dictionary<string, object>
            {
                ["documents_completed"] = completed,
                ["documents_failed"] = failed,
                ["bm25_indexed"] = bm25Ok,
                ["embedded"] = embedOk,
                ["graph_extracted"] = graphOk
            }
        });

        _logger.LogInformation(
            "ChunkAndExtract job {JobId} finished for {SourceId}: completed={Completed}, failed={Failed}, bm25={Bm25}, embed={Embed}, graph={Graph}",
            job.Id, sourceId, completed, failed, bm25Ok, embedOk, graphOk);

        return new JobResult
        {
            Status = JobTerminalStatus.Success,
            Metadata = new Dictionary<string, object>
            {
                ["documents_completed"] = completed,
                ["documents_failed"] = failed,
                ["bm25_indexed"] = bm25Ok,
                ["embedded"] = embedOk,
                ["graph_extracted"] = graphOk
            }
        };
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
            if (item is JsonElement je) s = je.GetString();
            else if (item is string s2) s = s2;
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

    private static string BuildContentPreview(string content)
    {
        if (string.IsNullOrWhiteSpace(content)) return string.Empty;
        var trimmed = content.Trim();
        return trimmed.Length <= 240 ? trimmed : trimmed[..240];
    }

    private static void ApplyCanonicalToDocument(
        DocumentEntity doc, CanonicalTextDocument canonical, long linkId, long? fetchItemId)
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
        doc.ProcessingStage = "chunk_and_extract";
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = "chunk_and_extract";
    }

    private static void MarkDocumentFailed(DocumentEntity doc, string stage, string? errorMessage = null)
    {
        doc.Status = "failed";
        doc.ProcessingStage = stage;
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = "chunk_and_extract";

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
        doc.UpdatedBy = "chunk_and_extract";

        var metadata = DeserializeMetadata(doc.Metadata);
        metadata["ingest_note"] = "empty_content_metadata_only";
        doc.Metadata = SerializeMetadata(metadata);
    }

    private static Dictionary<string, object> DeserializeMetadata(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
            return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var data = JsonSerializer.Deserialize<Dictionary<string, object?>>(json);
            if (data == null) return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            var result = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in data)
                if (item.Value != null) result[item.Key] = item.Value;
            return result;
        }
        catch { return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase); }
    }

    private static string SerializeMetadata(IReadOnlyDictionary<string, object> metadata)
        => metadata.Count == 0 ? "{}" : JsonSerializer.Serialize(metadata);

    private static string ComputeSha256(string input)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
