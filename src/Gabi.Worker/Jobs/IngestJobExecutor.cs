using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Microsoft.EntityFrameworkCore;

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
        var docs = await _context.Documents
            .Where(d => d.SourceId == sourceId && d.Status == "pending")
            .OrderBy(d => d.CreatedAt)
            .Take(5000)
            .ToListAsync(ct);

        if (docs.Count == 0)
        {
            progress.Report(new JobProgress { PercentComplete = 100, Message = "Nenhum documento pendente", Metrics = new Dictionary<string, object>() });
            return new JobResult { Success = true };
        }

        for (var i = 0; i < docs.Count; i++)
        {
            var doc = docs[i];
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

        _logger.LogInformation("Ingest finished for {SourceId}: {Count} docs completed", sourceId, docs.Count);
        return new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object> { ["documents_completed"] = docs.Count }
        };
    }
}

