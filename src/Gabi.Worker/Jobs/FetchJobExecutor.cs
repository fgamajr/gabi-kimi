using Gabi.Contracts.Jobs;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Stub executor for fetch phase. Enqueued via API; completes successfully so next phase can be triggered.
/// Replace with real fetch (download content for discovered links) when implementing.
/// </summary>
public class FetchJobExecutor : IJobExecutor
{
    public string JobType => "fetch";

    private readonly ILogger<FetchJobExecutor> _logger;

    public FetchJobExecutor(ILogger<FetchJobExecutor> logger) => _logger = logger;

    public Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        _logger.LogInformation("Fetch phase (stub) for source {SourceId} - not yet implemented", job.SourceId);
        progress.Report(new JobProgress { PercentComplete = 100, Message = "Stub: fetch not implemented", Metrics = new Dictionary<string, object>() });
        return Task.FromResult(new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object> { ["stub"] = true, ["message"] = "Fetch phase not yet implemented" }
        });
    }
}
