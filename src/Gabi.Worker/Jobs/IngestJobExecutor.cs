using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Microsoft.EntityFrameworkCore;
using System.Diagnostics;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Ingest executor: processa documentos pending da source e marca fase ingest.
/// </summary>
public class IngestJobExecutor : IJobExecutor
{
    public string JobType => "ingest";

    private readonly GabiDbContext _context;
    private readonly ILogger<IngestJobExecutor> _logger;

    public IngestJobExecutor(GabiDbContext context, ILogger<IngestJobExecutor> logger)
    {
        _context = context;
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
            .Take(5000)
            .ToListAsync(ct);
        parseActivity?.SetTag("docs.count", docs.Count);
        PipelineTelemetry.RecordDocsProcessed(docs.Count, sourceId, "parse");

        if (docs.Count == 0)
        {
            progress.Report(new JobProgress { PercentComplete = 100, Message = "Nenhum documento pendente", Metrics = new Dictionary<string, object>() });
            PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "parse");
            return new JobResult { Success = true };
        }

        using var chunkActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.chunk", ActivityKind.Internal);
        chunkActivity?.SetTag("source.id", sourceId);
        chunkActivity?.SetTag("docs.count", docs.Count);

        using var embedActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.embed", ActivityKind.Internal);
        embedActivity?.SetTag("source.id", sourceId);
        embedActivity?.SetTag("docs.count", docs.Count);

        using var indexActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.index", ActivityKind.Internal);
        indexActivity?.SetTag("source.id", sourceId);
        indexActivity?.SetTag("docs.count", docs.Count);

        try
        {
            for (var i = 0; i < docs.Count; i++)
            {
                var doc = docs[i];
                chunkActivity?.SetTag("document.id", doc.DocumentId ?? doc.Id.ToString());
                chunkActivity?.SetTag("document.url", doc.ContentUrl);
                doc.Status = "completed";
                doc.ProcessingStage = "ingested";
                doc.ProcessingStartedAt ??= DateTime.UtcNow;
                doc.ProcessingCompletedAt = DateTime.UtcNow;

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
                    Metrics = new Dictionary<string, object> { ["documents_total"] = docs.Count }
                });
            }
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

        _logger.LogInformation("Ingest finished for {SourceId}: {Count} docs completed", sourceId, docs.Count);
        PipelineTelemetry.RecordDocsProcessed(docs.Count, sourceId, "chunk");
        PipelineTelemetry.RecordDocsProcessed(docs.Count, sourceId, "embed");
        PipelineTelemetry.RecordDocsProcessed(docs.Count, sourceId, "index");
        PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "index");
        return new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object> { ["documents_completed"] = docs.Count }
        };
    }
}
