using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Ingest v2: normalize -> chunk -> embed -> index -> persist status.
/// Also keeps media projection (youtube/upload) into textual documents.
/// </summary>
public class IngestJobExecutor : IJobExecutor
{
    private const int MaxPendingDocsPerRun = 5000;
    private const int MaxMediaItemsPerRun = 1000;

    public string JobType => "ingest";

    private readonly GabiDbContext _context;
    private readonly ILogger<IngestJobExecutor> _logger;
    private readonly ICanonicalDocumentNormalizer _normalizer;
    private readonly IChunker _chunker;
    private readonly IEmbedder _embedder;
    private readonly IDocumentIndexer _indexer;
    private readonly IMediaTextProjector _mediaTextProjector;

    public IngestJobExecutor(
        GabiDbContext context,
        ICanonicalDocumentNormalizer normalizer,
        IChunker chunker,
        IEmbedder embedder,
        IDocumentIndexer indexer,
        IMediaTextProjector mediaTextProjector,
        ILogger<IngestJobExecutor> logger)
    {
        _context = context;
        _normalizer = normalizer;
        _chunker = chunker;
        _embedder = embedder;
        _indexer = indexer;
        _mediaTextProjector = mediaTextProjector;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var sourcePolicy = await LoadSourceIngestPolicyAsync(sourceId, ct);
        var stageStopwatch = Stopwatch.StartNew();
        using var parseActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.parse", ActivityKind.Internal);
        parseActivity?.SetTag("source.id", sourceId);
        parseActivity?.SetTag("ingest.readiness", sourcePolicy.Readiness);
        parseActivity?.SetTag("ingest.empty_content_action", sourcePolicy.EmptyContentAction);

        var docs = await _context.Documents
            .Where(d => d.SourceId == sourceId && d.Status == "pending")
            .OrderBy(d => d.CreatedAt)
            .Take(MaxPendingDocsPerRun)
            .ToListAsync(ct);
        parseActivity?.SetTag("docs.count", docs.Count);

        using var chunkActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.chunk", ActivityKind.Internal);
        chunkActivity?.SetTag("source.id", sourceId);
        chunkActivity?.SetTag("docs.count", docs.Count);

        using var embedActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.embed", ActivityKind.Internal);
        embedActivity?.SetTag("source.id", sourceId);
        embedActivity?.SetTag("docs.count", docs.Count);

        using var indexActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.index", ActivityKind.Internal);
        indexActivity?.SetTag("source.id", sourceId);
        indexActivity?.SetTag("docs.count", docs.Count);

        var docsCompleted = 0;
        var docsFailed = 0;
        var docsMetadataOnly = 0;
        var mediaProjected = 0;
        try
        {
            for (var i = 0; i < docs.Count; i++)
            {
                var doc = docs[i];
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
                    if (string.Equals(sourcePolicy.EmptyContentAction, "metadata_only", StringComparison.OrdinalIgnoreCase))
                    {
                        docsMetadataOnly++;
                        MarkDocumentMetadataOnly(doc);
                    }
                    else
                    {
                        docsFailed++;
                        MarkDocumentFailed(doc, "ingest_failed_empty_content");
                    }
                }
                else
                {
                    try
                    {
                        await ProcessCanonicalDocumentAsync(doc, canonical, chunkActivity, embedActivity, indexActivity, ct);
                        docsCompleted++;
                    }
                    catch (Exception ex)
                    {
                        docsFailed++;
                        MarkDocumentFailed(doc, "ingest_failed_v2_pipeline", ex.Message);
                    }
                }

                if (doc.FetchItemId.HasValue)
                {
                    var fetchItemId = doc.FetchItemId.Value;
                    var allDone = await _context.Documents
                        .Where(d => d.FetchItemId == fetchItemId)
                        .AllAsync(d => d.Id == doc.Id || d.Status == "completed", ct);
                    if (allDone)
                    {
                        await _context.DiscoveredLinks
                            .Where(l => l.Id == doc.LinkId)
                            .ExecuteUpdateAsync(setters => setters
                                .SetProperty(x => x.IngestStatus, "completed")
                                .SetProperty(x => x.UpdatedAt, DateTime.UtcNow), ct);
                    }
                }

                await _context.SaveChangesAsync(ct);

                progress.Report(new JobProgress
                {
                    PercentComplete = docs.Count == 0 ? 100 : (int)Math.Round(((i + 1) * 100.0) / docs.Count),
                    Message = $"Ingest {i + 1}/{docs.Count}",
                    Metrics = new Dictionary<string, object>
                    {
                        ["documents_total"] = docs.Count,
                        ["documents_completed"] = docsCompleted,
                        ["documents_failed"] = docsFailed,
                        ["documents_metadata_only"] = docsMetadataOnly
                    }
                });
            }

            mediaProjected = await ProjectMediaItemsAsDocumentsAsync(sourceId, progress, ct);
        }
        catch (Exception ex)
        {
            parseActivity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            chunkActivity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            embedActivity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            indexActivity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            parseActivity?.AddException(ex);
            chunkActivity?.AddException(ex);
            embedActivity?.AddException(ex);
            indexActivity?.AddException(ex);
            parseActivity?.SetTag("error.type", ex.GetType().Name);
            chunkActivity?.SetTag("error.type", ex.GetType().Name);
            embedActivity?.SetTag("error.type", ex.GetType().Name);
            indexActivity?.SetTag("error.type", ex.GetType().Name);
            throw;
        }

        var totalIngested = docsCompleted + mediaProjected;
        _logger.LogInformation(
            "Ingest v2 finished for {SourceId}: docs_completed={DocsCompleted}, docs_failed={DocsFailed}, docs_metadata_only={DocsMetadataOnly}, media_projected={MediaProjected}",
            sourceId,
            docsCompleted,
            docsFailed,
            docsMetadataOnly,
            mediaProjected);

        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "parse");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "chunk");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "embed");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "index");
        PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "index");

        const double maxDrift = 0.1;
        var pgActiveCount = await _context.Documents
            .CountAsync(d => d.SourceId == sourceId
                && d.RemovedFromSourceAt == null
                && (d.Status == "completed" || d.Status == "completed_metadata_only"), ct);
        var indexActiveCount = await _indexer.GetActiveDocumentCountAsync(sourceId, ct) ?? pgActiveCount;
        var driftRatio = pgActiveCount == 0 ? 0.0 : Math.Abs(pgActiveCount - indexActiveCount) / (double)pgActiveCount;
        var reconciliationStatus = driftRatio <= maxDrift ? "ok" : "drifted";

        _context.ReconciliationRecords.Add(new ReconciliationRecordEntity
        {
            RunId = job.Id,
            SourceId = sourceId,
            PgActiveCount = pgActiveCount,
            IndexActiveCount = indexActiveCount,
            DriftRatio = driftRatio,
            Status = reconciliationStatus,
            ReconciledAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync(ct);

        if (reconciliationStatus == "drifted")
        {
            _logger.LogWarning(
                "CODEX-D reconciliation drift for {SourceId}: ratio={DriftRatio:F2}, pg={PgCount}, index={IndexCount}, maxDrift={MaxDrift}",
                sourceId, driftRatio, pgActiveCount, indexActiveCount, maxDrift);
        }

        return new JobResult
        {
            Status = JobTerminalStatus.Success,
            Metadata = new Dictionary<string, object>
            {
                ["documents_completed"] = docsCompleted,
                ["documents_failed"] = docsFailed,
                ["documents_metadata_only"] = docsMetadataOnly,
                ["media_projected"] = mediaProjected,
                ["reconciliation_status"] = reconciliationStatus,
                ["reconciliation_drift_ratio"] = driftRatio
            }
        };
    }

    private async Task ProcessCanonicalDocumentAsync(
        DocumentEntity doc,
        CanonicalTextDocument canonical,
        Activity? chunkActivity,
        Activity? embedActivity,
        Activity? indexActivity,
        CancellationToken ct)
    {
        var chunkMetadata = new Dictionary<string, object>(canonical.Metadata, StringComparer.OrdinalIgnoreCase)
        {
            ["source_id"] = canonical.SourceId,
            ["external_id"] = canonical.ExternalId
        };

        var chunkConfig = new ChunkConfig
        {
            Strategy = "fixed",
            MaxChunkSize = 512,
            Overlap = 64
        };

        var chunkResult = _chunker.Chunk(canonical.Content, chunkConfig, chunkMetadata);
        if (chunkResult.Chunks.Count == 0)
            throw new InvalidOperationException("Chunking returned zero chunks for non-empty content.");

        chunkActivity?.SetTag("chunks.count", chunkResult.Chunks.Count);
        chunkActivity?.SetTag("chunks.tokens", chunkResult.TotalTokens);

        var embeddings = await _embedder.EmbedChunksAsync(chunkResult.Chunks, doc.Id.ToString(), ct);
        embedActivity?.SetTag("embeddings.count", embeddings.TotalEmbeddings);
        embedActivity?.SetTag("embeddings.model", embeddings.Model);

        var indexDocument = BuildIndexDocument(doc, canonical, chunkResult.Chunks.Count);
        var indexChunks = BuildIndexChunks(embeddings);
        var indexingResult = await _indexer.IndexAsync(indexDocument, indexChunks, ct);

        indexActivity?.SetTag("index.status", indexingResult.Status.ToString().ToLowerInvariant());
        indexActivity?.SetTag("index.chunks", indexingResult.ChunksIndexed);

        if (indexingResult.Status is IndexingStatus.Failed or IndexingStatus.RolledBack)
        {
            var message = indexingResult.Errors.Count > 0
                ? string.Join("; ", indexingResult.Errors)
                : "Indexing failed without explicit error";
            throw new InvalidOperationException(message);
        }

        var enrichedCanonical = canonical with
        {
            Metadata = EnrichMetadataForIngestV2(canonical.Metadata, chunkConfig, chunkResult, embeddings, indexingResult)
        };

        ApplyCanonicalToDocument(doc, enrichedCanonical, doc.LinkId, doc.FetchItemId, "ingest_v2", "ingested_v2");
        doc.ElasticsearchId = indexDocument.DocumentId;
    }

    private async Task<int> ProjectMediaItemsAsDocumentsAsync(
        string sourceId,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        var mediaItems = await _context.MediaItems
            .Where(m => m.SourceId == sourceId
                && m.TranscriptStatus == "completed"
                && (!string.IsNullOrWhiteSpace(m.TranscriptText) || !string.IsNullOrWhiteSpace(m.SummaryText)))
            .OrderBy(m => m.CreatedAt)
            .Take(MaxMediaItemsPerRun)
            .ToListAsync(ct);

        if (mediaItems.Count == 0)
            return 0;

        var projected = 0;
        for (var i = 0; i < mediaItems.Count; i++)
        {
            var media = mediaItems[i];
            var mediaMetadata = DeserializeMetadata(media.Metadata);
            var projectedHash = mediaMetadata.TryGetValue("ingest_projected_hash", out var existingHashObj)
                ? Convert.ToString(existingHashObj)
                : null;

            var canonical = _mediaTextProjector.Project(new MediaProjectionInput
            {
                SourceId = media.SourceId,
                ExternalId = media.ExternalId,
                MediaUrl = media.MediaUrl,
                Title = media.Title,
                TranscriptText = media.TranscriptText,
                SummaryText = media.SummaryText,
                SessionType = media.SessionType,
                Chamber = media.Chamber,
                DurationSeconds = media.DurationSeconds,
                TranscriptConfidence = media.TranscriptConfidence,
                Metadata = mediaMetadata
            });

            var contentHash = ComputeSha256(canonical.Content);
            if (string.Equals(projectedHash, contentHash, StringComparison.OrdinalIgnoreCase))
                continue;

            var mediaUrl = string.IsNullOrWhiteSpace(media.MediaUrl)
                ? $"media://{media.SourceId}/{media.ExternalId}"
                : media.MediaUrl!;

            var link = await EnsureMediaLinkAsync(media, mediaUrl, ct);
            var doc = await _context.Documents
                .FirstOrDefaultAsync(d => d.SourceId == media.SourceId && d.ExternalId == media.ExternalId, ct);

            if (doc == null)
            {
                doc = new DocumentEntity
                {
                    LinkId = link.Id,
                    FetchItemId = null,
                    SourceId = media.SourceId,
                    DocumentId = media.ExternalId,
                    ExternalId = media.ExternalId,
                    CreatedAt = DateTime.UtcNow,
                    CreatedBy = "ingest_v1"
                };
                _context.Documents.Add(doc);
            }

            ApplyCanonicalToDocument(doc, canonical, link.Id, null);
            doc.SourceContentHash = contentHash;

            var updatedMediaMetadata = new Dictionary<string, object>(mediaMetadata, StringComparer.OrdinalIgnoreCase)
            {
                ["ingest_projected_hash"] = contentHash,
                ["ingest_projected_at"] = DateTime.UtcNow.ToString("O"),
                ["ingest_document_external_id"] = media.ExternalId
            };
            media.Metadata = SerializeMetadata(updatedMediaMetadata);
            media.UpdatedAt = DateTime.UtcNow;
            media.UpdatedBy = "ingest_v1";

            link.IngestStatus = "completed";
            link.FetchStatus = "completed";
            link.Status = "completed";
            link.LastProcessedAt = DateTime.UtcNow;
            link.UpdatedAt = DateTime.UtcNow;
            link.UpdatedBy = "ingest_v1";

            projected++;
            if (projected % 50 == 0)
            {
                await _context.SaveChangesAsync(ct);
                progress.Report(new JobProgress
                {
                    PercentComplete = 100,
                    Message = $"Ingest media projection {projected}/{mediaItems.Count}",
                    Metrics = new Dictionary<string, object> { ["media_projected"] = projected }
                });
            }
        }

        await _context.SaveChangesAsync(ct);
        return projected;
    }

    private async Task<DiscoveredLinkEntity> EnsureMediaLinkAsync(MediaItemEntity media, string mediaUrl, CancellationToken ct)
    {
        var urlHash = ComputeSha256(mediaUrl);
        var link = await _context.DiscoveredLinks
            .FirstOrDefaultAsync(l => l.SourceId == media.SourceId && l.UrlHash == urlHash, ct);
        if (link != null)
            return link;

        var linkMetadata = new Dictionary<string, object>
        {
            ["origin"] = "media_projection_v1",
            ["media_item_id"] = media.Id,
            ["media_external_id"] = media.ExternalId
        };

        link = new DiscoveredLinkEntity
        {
            SourceId = media.SourceId,
            Url = mediaUrl,
            UrlHash = urlHash,
            FirstSeenAt = DateTime.UtcNow,
            DiscoveredAt = DateTime.UtcNow,
            Status = "completed",
            DiscoveryStatus = "completed",
            FetchStatus = "completed",
            IngestStatus = "pending",
            Metadata = SerializeMetadata(linkMetadata),
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow,
            CreatedBy = "ingest_v1",
            UpdatedBy = "ingest_v1"
        };

        _context.DiscoveredLinks.Add(link);
        await _context.SaveChangesAsync(ct);
        return link;
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

    private async Task<SourceIngestPolicy> LoadSourceIngestPolicyAsync(string sourceId, CancellationToken ct)
    {
        var sourcesPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH") ?? "sources_v2.yaml";
        if (!File.Exists(sourcesPath))
            sourcesPath = Path.Combine(Directory.GetCurrentDirectory(), sourcesPath);

        if (!File.Exists(sourcesPath))
            return SourceIngestPolicy.Default;

        try
        {
            var yaml = await File.ReadAllTextAsync(sourcesPath, ct);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();

            var root = deserializer.Deserialize<Dictionary<object, object>>(yaml);
            if (root == null)
                return SourceIngestPolicy.Default;

            var defaultPolicy = ResolveDefaultIngestPolicy(root);

            if (!TryGetMap(root, "sources", out var sources)
                || !sources.TryGetValue(sourceId, out var sourceObj)
                || sourceObj is not Dictionary<object, object> source)
            {
                return defaultPolicy;
            }

            if (!TryGetMap(source, "pipeline", out var pipeline)
                || !TryGetMap(pipeline, "ingest", out var sourceIngest))
            {
                return defaultPolicy;
            }

            return MergeIngestPolicy(defaultPolicy, sourceIngest);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to load source ingest policy for {SourceId}", sourceId);
            return SourceIngestPolicy.Default;
        }
    }

    private static SourceIngestPolicy ResolveDefaultIngestPolicy(Dictionary<object, object> root)
    {
        if (!TryGetMap(root, "defaults", out var defaults)
            || !TryGetMap(defaults, "pipeline", out var defaultPipeline)
            || !TryGetMap(defaultPipeline, "ingest", out var defaultIngest))
        {
            return SourceIngestPolicy.Default;
        }

        return MergeIngestPolicy(SourceIngestPolicy.Default, defaultIngest);
    }

    private static SourceIngestPolicy MergeIngestPolicy(SourceIngestPolicy fallback, Dictionary<object, object> ingest)
    {
        var readiness = ingest.TryGetValue("readiness", out var readinessObj)
            ? readinessObj?.ToString()
            : fallback.Readiness;

        var emptyContentAction = ingest.TryGetValue("empty_content_action", out var actionObj)
            ? actionObj?.ToString()
            : fallback.EmptyContentAction;

        return new SourceIngestPolicy(
            NormalizeReadiness(readiness),
            NormalizeEmptyContentAction(emptyContentAction));
    }

    private static bool TryGetMap(
        IReadOnlyDictionary<object, object> map,
        string key,
        out Dictionary<object, object> value)
    {
        if (map.TryGetValue(key, out var obj) && obj is Dictionary<object, object> typed)
        {
            value = typed;
            return true;
        }

        value = new Dictionary<object, object>();
        return false;
    }

    private static string NormalizeReadiness(string? readiness)
    {
        if (string.Equals(readiness, "metadata_only", StringComparison.OrdinalIgnoreCase))
            return "metadata_only";
        return "text_ready";
    }

    private static string NormalizeEmptyContentAction(string? emptyContentAction)
    {
        if (string.Equals(emptyContentAction, "metadata_only", StringComparison.OrdinalIgnoreCase))
            return "metadata_only";
        return "fail";
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
        ChunkConfig chunkConfig,
        ChunkResult chunkResult,
        EmbeddingResult embeddings,
        IndexingResult indexingResult)
    {
        var metadata = new Dictionary<string, object>(existingMetadata, StringComparer.OrdinalIgnoreCase)
        {
            ["ingest_version"] = "v2",
            ["ingest_chunk_strategy"] = chunkConfig.Strategy,
            ["ingest_chunk_size"] = chunkConfig.MaxChunkSize,
            ["ingest_chunk_overlap"] = chunkConfig.Overlap,
            ["ingest_chunk_count"] = chunkResult.Chunks.Count,
            ["ingest_total_tokens"] = chunkResult.TotalTokens,
            ["ingest_embedding_model"] = embeddings.Model,
            ["ingest_embedding_dimensions"] = embeddings.Chunks.FirstOrDefault()?.Dimensions ?? 0,
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
        return metadata.Count == 0
            ? "{}"
            : JsonSerializer.Serialize(metadata);
    }

    private static string ComputeSha256(string input)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private sealed record SourceIngestPolicy(string Readiness, string EmptyContentAction)
    {
        public static SourceIngestPolicy Default { get; } = new("text_ready", "fail");
    }
}
