using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job executor for source sync/discovery jobs.
/// </summary>
public class SourceSyncJobExecutor : IJobExecutor
{
    public string JobType => "sync";

    private readonly IDiscoveredLinkRepository _linkRepository;
    private readonly ILogger<SourceSyncJobExecutor> _logger;
    private readonly DiscoveryEngine _discoveryEngine;

    public SourceSyncJobExecutor(
        IDiscoveredLinkRepository linkRepository,
        ILogger<SourceSyncJobExecutor> logger)
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
                "Starting discovery for source {SourceId} with strategy {Strategy}",
                sourceId, discoveryConfig.Mode);

            progress.Report(new JobProgress
            {
                PercentComplete = 0,
                Message = "Iniciando descoberta...",
                Metrics = new Dictionary<string, object>()
            });

            // Discovery phase
            var discoveredUrls = new List<DiscoveredSource>();
            await foreach (var discovered in _discoveryEngine.DiscoverAsync(sourceId, discoveryConfig, ct))
            {
                discoveredUrls.Add(discovered);

                // Report progress every 10 URLs
                if (discoveredUrls.Count % 10 == 0)
                {
                    progress.Report(new JobProgress
                    {
                        PercentComplete = 10,
                        Message = $"Descobrindo... ({discoveredUrls.Count} links encontrados)",
                        Metrics = new Dictionary<string, object> { ["linksFound"] = discoveredUrls.Count }
                    });
                }
            }

            _logger.LogInformation(
                "Discovered {Count} URLs for source {SourceId}",
                discoveredUrls.Count, sourceId);

            progress.Report(new JobProgress
            {
                PercentComplete = 50,
                Message = $"Salvando {discoveredUrls.Count} links...",
                Metrics = new Dictionary<string, object> { ["linksFound"] = discoveredUrls.Count }
            });

            // Save discovered links to database
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
            _logger.LogError(ex, "Job failed for source {SourceId}", job.SourceId);
            return new JobResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                ErrorType = ex.GetType().Name
            };
        }
    }
}
