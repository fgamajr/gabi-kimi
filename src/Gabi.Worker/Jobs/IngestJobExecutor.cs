using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Ingest v1: normalize -> validate -> upsert textual document.
/// For media items (youtube/upload), project transcript + metadata into textual documents.
/// </summary>
public class IngestJobExecutor : IJobExecutor
{
    private const int MaxPendingDocsPerRun = 5000;
    private const int MaxMediaItemsPerRun = 1000;

    public string JobType => "ingest";

    private readonly GabiDbContext _context;
    private readonly ILogger<IngestJobExecutor> _logger;
    private readonly ICanonicalDocumentNormalizer _normalizer;
    private readonly IMediaTextProjector _mediaTextProjector;

    public IngestJobExecutor(
        GabiDbContext context,
        ICanonicalDocumentNormalizer normalizer,
        IMediaTextProjector mediaTextProjector,
        ILogger<IngestJobExecutor> logger)
    {
        _context = context;
        _normalizer = normalizer;
        _mediaTextProjector = mediaTextProjector;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var stageStopwatch = Stopwatch.StartNew();
        using var parseActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.parse", ActivityKind.Internal);
        parseActivity?.SetTag("source.id", sourceId);

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
                    docsFailed++;
                    doc.Status = "failed";
                    doc.ProcessingStage = "ingest_failed_empty_content";
                    doc.ProcessingStartedAt ??= DateTime.UtcNow;
                    doc.ProcessingCompletedAt = DateTime.UtcNow;
                    doc.UpdatedAt = DateTime.UtcNow;
                    doc.UpdatedBy = "ingest_v1";
                }
                else
                {
                    ApplyCanonicalToDocument(doc, canonical, doc.LinkId, doc.FetchItemId);
                    docsCompleted++;
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
                    PercentComplete = (int)Math.Round(((i + 1) * 100.0) / docs.Count),
                    Message = $"Ingest {i + 1}/{docs.Count}",
                    Metrics = new Dictionary<string, object>
                    {
                        ["documents_total"] = docs.Count,
                        ["documents_completed"] = docsCompleted,
                        ["documents_failed"] = docsFailed
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
            "Ingest v1 finished for {SourceId}: docs_completed={DocsCompleted}, docs_failed={DocsFailed}, media_projected={MediaProjected}",
            sourceId,
            docsCompleted,
            docsFailed,
            mediaProjected);

        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "parse");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "chunk");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "embed");
        PipelineTelemetry.RecordDocsProcessed(totalIngested, sourceId, "index");
        PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "index");

        return new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object>
            {
                ["documents_completed"] = docsCompleted,
                ["documents_failed"] = docsFailed,
                ["media_projected"] = mediaProjected
            }
        };
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

    private static void ApplyCanonicalToDocument(
        DocumentEntity doc,
        CanonicalTextDocument canonical,
        long linkId,
        long? fetchItemId)
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
        doc.ProcessingStage = "ingested";
        doc.ProcessingStartedAt ??= DateTime.UtcNow;
        doc.ProcessingCompletedAt = DateTime.UtcNow;
        doc.UpdatedAt = DateTime.UtcNow;
        doc.UpdatedBy = "ingest_v1";
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
}
