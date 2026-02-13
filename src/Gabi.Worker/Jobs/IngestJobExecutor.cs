using Gabi.Contracts.Jobs;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Stub executor for ingest phase. Enqueued via API; completes successfully so pipeline can progress.
/// Replace with real ingest (parse, index documents) when implementing.
/// </summary>
public class IngestJobExecutor : IJobExecutor
{
    public string JobType => "ingest";

    private readonly ILogger<IngestJobExecutor> _logger;

    public IngestJobExecutor(ILogger<IngestJobExecutor> logger) => _logger = logger;

    public Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        _logger.LogInformation("Ingest phase (stub) for source {SourceId} - not yet implemented", job.SourceId);
        progress.Report(new JobProgress { PercentComplete = 100, Message = "Stub: ingest not implemented", Metrics = new Dictionary<string, object>() });
        return Task.FromResult(new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object> { ["stub"] = true, ["message"] = "Ingest phase not yet implemented" }
        });
    }
}
