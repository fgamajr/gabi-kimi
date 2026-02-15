using System.Collections.Generic;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Polly;
using Polly.Retry;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job executor for source_discovery jobs (enqueued by dashboard refresh).
/// Uses Polly retry (exponential backoff) and failsafe: 0 links from engine is success (LinksTotal=0).
/// Persists links with DiscoveryStatus=completed, FetchStatus=IngestStatus=pending; records run in discovery_runs.
/// </summary>
public class SourceDiscoveryJobExecutor : IJobExecutor
{
    public string JobType => "source_discovery";

    private readonly IDiscoveredLinkRepository _linkRepository;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly GabiDbContext _context;
    private readonly ILogger<SourceDiscoveryJobExecutor> _logger;
    private readonly DiscoveryEngine _discoveryEngine;

    private const int MaxRetryAttempts = 3;
    private static readonly TimeSpan InitialRetryDelay = TimeSpan.FromSeconds(1);

    private static readonly ResiliencePipeline _retryPipeline = new ResiliencePipelineBuilder()
        .AddRetry(new RetryStrategyOptions
        {
            MaxRetryAttempts = MaxRetryAttempts,
            Delay = TimeSpan.FromSeconds(1),
            BackoffType = DelayBackoffType.Exponential,
            UseJitter = true,
            OnRetry = args =>
            {
                // Log from executor
                return ValueTask.CompletedTask;
            }
        })
        .Build();

    public SourceDiscoveryJobExecutor(
        IDiscoveredLinkRepository linkRepository,
        IFetchItemRepository fetchItemRepository,
        GabiDbContext context,
        ILogger<SourceDiscoveryJobExecutor> logger)
    {
        _linkRepository = linkRepository;
        _fetchItemRepository = fetchItemRepository;
        _context = context;
        _logger = logger;
        _discoveryEngine = new DiscoveryEngine();
    }

    public async Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var discoveryConfig = job.DiscoveryConfig ?? new DiscoveryConfig();
        var startedAt = DateTime.UtcNow;

        _logger.LogInformation(
            "Starting discovery (source_discovery) for source {SourceId} with strategy {Strategy}",
            sourceId, discoveryConfig.Strategy ?? "unknown");

        progress.Report(new JobProgress
        {
            PercentComplete = 0,
            Message = "Iniciando descoberta...",
            Metrics = new Dictionary<string, object>()
        });

        List<DiscoveredSource> discoveredUrls;
        try
        {
            discoveredUrls = await _retryPipeline.ExecuteAsync(async token =>
            {
                var list = new List<DiscoveredSource>();
                await foreach (var discovered in _discoveryEngine.DiscoverAsync(sourceId, discoveryConfig, token))
                {
                    list.Add(discovered);
                    if (list.Count % 10 == 0)
                    {
                        progress.Report(new JobProgress
                        {
                            PercentComplete = Math.Min(40, list.Count),
                            Message = $"Descobrindo... ({list.Count} links)",
                            Metrics = new Dictionary<string, object> { ["linksFound"] = list.Count }
                        });
                    }
                }
                return list;
            }, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Discovery job failed for source {SourceId} after retries", sourceId);
            var discoveryRun = new DiscoveryRunEntity
            {
                Id = Guid.NewGuid(),
                JobId = job.Id,
                SourceId = sourceId,
                StartedAt = startedAt,
                CompletedAt = DateTime.UtcNow,
                LinksTotal = 0,
                Status = "failed",
                ErrorSummary = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message
            };
            _context.DiscoveryRuns.Add(discoveryRun);
            await _context.SaveChangesAsync(ct);
            return new JobResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                ErrorType = ex.GetType().Name
            };
        }

        // Failsafe: 0 links is success (e.g. web_crawl / api_pagination not implemented yet)
        var linksTotal = discoveredUrls.Count;

        progress.Report(new JobProgress
        {
            PercentComplete = 50,
            Message = linksTotal > 0 ? $"Salvando {linksTotal} links..." : "Nenhum link descoberto (registrando run).",
            Metrics = new Dictionary<string, object> { ["linksFound"] = linksTotal }
        });

        if (linksTotal > 0)
        {
            var linksToUpsert = discoveredUrls.Select(d => new DiscoveredLinkEntity
            {
                SourceId = sourceId,
                Url = d.Url,
                DiscoveredAt = d.DiscoveredAt,
                FirstSeenAt = d.DiscoveredAt,
                Etag = d.Etag,
                Status = LinkStatus.Pending.ToString().ToLowerInvariant(),
                DiscoveryStatus = "completed",
                FetchStatus = "pending",
                IngestStatus = "pending",
                Metadata = "{}"
            }).ToList();

            await _linkRepository.BulkUpsertAsync(linksToUpsert, ct);

            var urlHashes = linksToUpsert.Select(l => l.UrlHash).ToList();
            var persistedLinks = await _context.DiscoveredLinks
                .Where(l => l.SourceId == sourceId && urlHashes.Contains(l.UrlHash))
                .ToListAsync(ct);
            await _fetchItemRepository.EnsurePendingForLinksAsync(persistedLinks, ct);
        }

        var runStatus = "completed";
        var discoveryRunEntity = new DiscoveryRunEntity
        {
            Id = Guid.NewGuid(),
            JobId = job.Id,
            SourceId = sourceId,
            StartedAt = startedAt,
            CompletedAt = DateTime.UtcNow,
            LinksTotal = linksTotal,
            Status = runStatus,
            ErrorSummary = null
        };
        _context.DiscoveryRuns.Add(discoveryRunEntity);
        await _context.SaveChangesAsync(ct);

        progress.Report(new JobProgress
        {
            PercentComplete = 100,
            Message = "Concluído",
            Metrics = new Dictionary<string, object> { ["linksFound"] = linksTotal, ["discoveryRunId"] = discoveryRunEntity.Id.ToString() }
        });

        _logger.LogInformation(
            "Discovery completed for source {SourceId}: {LinksTotal} links, status={Status}",
            sourceId, linksTotal, runStatus);

        return new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object>
            {
                ["urls_discovered"] = linksTotal,
                ["source_id"] = sourceId,
                ["discovery_run_id"] = discoveryRunEntity.Id.ToString()
            }
        };
    }
}
