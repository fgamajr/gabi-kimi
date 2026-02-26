using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Ingest v2: fan-out only. Queries pending document IDs, batches into 32-64, enqueues EmbedAndIndex jobs.
/// Keeps media projection and reconciliation. Embed/index run in EmbedAndIndexJobExecutor (embed queue).
/// </summary>
public class IngestJobExecutor : IJobExecutor
{
    private const int MaxPendingDocsPerRun = 5000;
    private const int EmbedFanOutPageSize = 200;
    private const int MaxMediaItemsPerRun = 1000;

    public string JobType => "ingest";

    private readonly GabiDbContext _context;
    private readonly ILogger<IngestJobExecutor> _logger;
    private readonly ICanonicalDocumentNormalizer _normalizer;
    private readonly IDocumentIndexer _indexer;
    private readonly IMediaTextProjector _mediaTextProjector;
    private readonly IJobQueueRepository _jobQueue;
    private readonly IDocumentRepository _docRepository;

    public IngestJobExecutor(
        GabiDbContext context,
        ICanonicalDocumentNormalizer normalizer,
        IDocumentIndexer indexer,
        IMediaTextProjector mediaTextProjector,
        IJobQueueRepository jobQueue,
        IDocumentRepository docRepository,
        ILogger<IngestJobExecutor> logger)
    {
        _context = context;
        _normalizer = normalizer;
        _indexer = indexer;
        _mediaTextProjector = mediaTextProjector;
        _jobQueue = jobQueue;
        _docRepository = docRepository;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var stageStopwatch = Stopwatch.StartNew();
        using var parseActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.ingest_fanout", ActivityKind.Internal);
        parseActivity?.SetTag("source.id", sourceId);

        var totalPending = await _context.Documents
            .CountAsync(d => d.SourceId == sourceId && d.Status == "pending", ct);
        var totalCap = Math.Min(MaxPendingDocsPerRun, totalPending);
        parseActivity?.SetTag("docs.count", totalCap);

        if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
        {
            _logger.LogInformation("Ingest fan-out skipped for {SourceId}: source is paused or stopped", sourceId);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object> { ["interrupted_by"] = "pause", ["document_ids_enqueued"] = 0 }
            };
        }

        var backpressure = PipelineBackpressureConfig.Load();
        var pendingEmbed = await _context.JobRegistry
            .CountAsync(r => r.SourceId == sourceId && r.JobType == "embed_and_index"
                && (r.Status == "pending" || r.Status == "processing"), ct);
        if (pendingEmbed > backpressure.MaxPendingEmbed)
        {
            _logger.LogInformation(
                "Ingest yielding for {SourceId}: backpressure pending_embed={Pending} > {Max}",
                sourceId, pendingEmbed, backpressure.MaxPendingEmbed);
            var retryJob = new IngestJob
            {
                Id = Guid.NewGuid(),
                SourceId = sourceId,
                JobType = "ingest",
                Payload = job.Payload ?? new Dictionary<string, object>()
            };
            await _jobQueue.ScheduleAsync(retryJob, TimeSpan.FromSeconds(60), ct);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object>
                {
                    ["yielded"] = true,
                    ["reason"] = "backpressure",
                    ["pending_downstream"] = pendingEmbed
                }
            };
        }

        var embedConfig = PipelineEmbedBatchConfig.Load();
        var batchesEnqueued = 0;
        var documentIdsEnqueued = 0;
        var mediaProjected = 0;
        var interruptedByPause = false;
        try
        {
            var lastId = Guid.Empty;
            while (documentIdsEnqueued < totalCap)
            {
                if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
                {
                    _logger.LogInformation("Ingest fan-out interrupted for {SourceId}: source paused/stopped at {Enqueued} docs", sourceId, documentIdsEnqueued);
                    interruptedByPause = true;
                    break;
                }

                var remaining = totalCap - documentIdsEnqueued;
                var page = await _context.Documents
                    .Where(d => d.SourceId == sourceId && d.Status == "pending" && d.Id.CompareTo(lastId) > 0)
                    .OrderBy(d => d.Id)
                    .Take(Math.Min(EmbedFanOutPageSize, remaining))
                    .Select(d => new { d.Id, ContentLength = d.Content != null ? d.Content.Length : 0 })
                    .ToListAsync(ct);

                if (page.Count == 0)
                    break;

                var pageTuples = page.Select(x => (x.Id, x.ContentLength)).ToList();
                var batches = FormBatches(pageTuples, embedConfig);
                foreach (var batchIds in batches)
                {
                    if (batchIds.Count == 0) continue;
                    var payload = new Dictionary<string, object>
                    {
                        ["document_ids"] = batchIds.Select(g => g.ToString()).ToList()
                    };
                    var embedJob = new IngestJob
                    {
                        Id = Guid.NewGuid(),
                        SourceId = sourceId,
                        JobType = "embed_and_index",
                        Payload = payload
                    };
                    await _jobQueue.EnqueueAsync(embedJob, ct);
                    batchesEnqueued++;
                    documentIdsEnqueued += batchIds.Count;

                    progress.Report(new JobProgress
                    {
                        PercentComplete = totalCap == 0 ? 100 : Math.Min(100, (int)Math.Round((documentIdsEnqueued * 100.0) / totalCap)),
                        Message = $"Ingest fan-out {documentIdsEnqueued}/{totalCap}",
                        Metrics = new Dictionary<string, object>
                        {
                            ["documents_total"] = totalCap,
                            ["batches_enqueued"] = batchesEnqueued,
                            ["document_ids_enqueued"] = documentIdsEnqueued
                        }
                    });
                }

                lastId = page[page.Count - 1].Id;
            }

            mediaProjected = await ProjectMediaItemsAsDocumentsAsync(sourceId, progress, ct);
        }
        catch (Exception ex)
        {
            parseActivity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            parseActivity?.AddException(ex);
            parseActivity?.SetTag("error.type", ex.GetType().Name);
            PipelineTelemetry.RecordStageError(sourceId, "ingest");
            throw;
        }

        _logger.LogInformation(
            "Ingest fan-out finished for {SourceId}: batches_enqueued={Batches}, document_ids_enqueued={Ids}, media_projected={MediaProjected}",
            sourceId, batchesEnqueued, documentIdsEnqueued, mediaProjected);

        PipelineTelemetry.RecordDocsProcessed(documentIdsEnqueued + mediaProjected, sourceId, "parse");
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

        var resultMetadata = new Dictionary<string, object>
        {
            ["batches_enqueued"] = batchesEnqueued,
            ["document_ids_enqueued"] = documentIdsEnqueued,
            ["media_projected"] = mediaProjected,
            ["reconciliation_status"] = reconciliationStatus,
            ["reconciliation_drift_ratio"] = driftRatio
        };
        if (interruptedByPause)
            resultMetadata["interrupted_by"] = "pause";
        return new JobResult { Status = JobTerminalStatus.Success, Metadata = resultMetadata };
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
                await _docRepository.AddAsync(doc, ct);
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

    /// <summary>
    /// Splits a page of (Id, ContentLength) into batches respecting max chars and max docs per batch.
    /// </summary>
    private static List<List<Guid>> FormBatches(
        List<(Guid Id, int ContentLength)> page,
        PipelineEmbedBatchConfig config)
    {
        var result = new List<List<Guid>>();
        var currentBatch = new List<Guid>();
        var currentChars = 0;

        foreach (var item in page)
        {
            var wouldExceedChars = currentChars + item.ContentLength > config.MaxCharsPerBatch;
            if (currentBatch.Count >= config.MinDocsPerBatch && wouldExceedChars)
            {
                if (currentBatch.Count > 0)
                {
                    result.Add(currentBatch);
                    currentBatch = new List<Guid>();
                    currentChars = 0;
                }
            }
            if (currentBatch.Count >= config.MaxDocsPerBatch)
            {
                result.Add(currentBatch);
                currentBatch = new List<Guid>();
                currentChars = 0;
            }
            currentBatch.Add(item.Id);
            currentChars += item.ContentLength;
        }

        if (currentBatch.Count > 0)
            result.Add(currentBatch);
        return result;
    }

    private sealed record SourceIngestPolicy(string Readiness, string EmptyContentAction)
    {
        public static SourceIngestPolicy Default { get; } = new("text_ready", "fail");
    }
}
