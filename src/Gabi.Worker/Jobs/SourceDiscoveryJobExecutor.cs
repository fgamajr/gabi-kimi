using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job executor for source_discovery jobs (enqueued by dashboard refresh).
/// Uses same discovery + persist logic as SourceSyncJobExecutor; DiscoveryConfig comes from job.Payload in MapToIngestJob.
/// </summary>
public class SourceDiscoveryJobExecutor : IJobExecutor
{
    public string JobType => "source_discovery";

    private readonly IDiscoveredLinkRepository _linkRepository;
    private readonly ILogger<SourceDiscoveryJobExecutor> _logger;
    private readonly DiscoveryEngine _discoveryEngine;

    public SourceDiscoveryJobExecutor(
        IDiscoveredLinkRepository linkRepository,
        ILogger<SourceDiscoveryJobExecutor> logger)
    {
        _linkRepository = linkRepository;
        _logger = logger;
        _discoveryEngine = new DiscoveryEngine();
    }

    public async Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        try
        {
            var sourceId = job.SourceId;
            var discoveryConfig = job.DiscoveryConfig;

            _logger.LogInformation(
                "Starting discovery (source_discovery) for source {SourceId} with strategy {Strategy}",
                sourceId, discoveryConfig?.Strategy ?? "unknown");

            progress.Report(new JobProgress
            {
                PercentComplete = 0,
                Message = "Iniciando descoberta...",
                Metrics = new Dictionary<string, object>()
            });

            var discoveredUrls = new List<DiscoveredSource>();
            await foreach (var discovered in _discoveryEngine.DiscoverAsync(sourceId, discoveryConfig ?? new DiscoveryConfig(), ct))
            {
                discoveredUrls.Add(discovered);

                if (discoveredUrls.Count % 10 == 0)
                {
                    progress.Report(new JobProgress
                    {
                        PercentComplete = Math.Min(40, discoveredUrls.Count),
                        Message = $"Descobrindo... ({discoveredUrls.Count} links)",
                        Metrics = new Dictionary<string, object> { ["linksFound"] = discoveredUrls.Count }
                    });
                }
            }

            progress.Report(new JobProgress
            {
                PercentComplete = 50,
                Message = $"Salvando {discoveredUrls.Count} links...",
                Metrics = new Dictionary<string, object> { ["linksFound"] = discoveredUrls.Count }
            });

            var linksToInsert = discoveredUrls.Select(d => new DiscoveredLinkEntity
            {
                SourceId = sourceId,
                Url = d.Url,
                DiscoveredAt = d.DiscoveredAt,
                FirstSeenAt = d.DiscoveredAt,
                Etag = d.Etag,
                Status = LinkStatus.Pending.ToString().ToLowerInvariant(),
                Metadata = "{}"
            }).ToList();

            if (linksToInsert.Any())
            {
                await _linkRepository.BulkInsertAsync(linksToInsert, ct);
            }

            progress.Report(new JobProgress
            {
                PercentComplete = 100,
                Message = "Concluído",
                Metrics = new Dictionary<string, object> { ["linksFound"] = discoveredUrls.Count }
            });

            return new JobResult
            {
                Success = true,
                Metadata = new Dictionary<string, object>
                {
                    ["urls_discovered"] = discoveredUrls.Count,
                    ["source_id"] = sourceId
                }
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Discovery job failed for source {SourceId}", job.SourceId);
            return new JobResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                ErrorType = ex.GetType().Name
            };
        }
    }
}
