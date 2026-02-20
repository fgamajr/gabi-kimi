using System.Collections.Generic;
using System.Text.Json;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job executor for source_discovery jobs (enqueued by dashboard refresh).
/// Retry handled by Hangfire global policy (configured in Worker Hangfire:RetryPolicy).
/// Failsafe: 0 links from engine is success (LinksTotal=0) but logs warning.
/// Persists links with DiscoveryStatus=completed, FetchStatus=IngestStatus=pending; records run in discovery_runs.
/// </summary>
public class SourceDiscoveryJobExecutor : IJobExecutor
{
    public string JobType => "source_discovery";
    private const int DiscoveryBatchSize = 1000;

    private readonly IDiscoveredLinkRepository _linkRepository;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly GabiDbContext _context;
    private readonly ILogger<SourceDiscoveryJobExecutor> _logger;
    private readonly DiscoveryEngine _discoveryEngine;

    public SourceDiscoveryJobExecutor(
        IDiscoveredLinkRepository linkRepository,
        IFetchItemRepository fetchItemRepository,
        GabiDbContext context,
        DiscoveryEngine discoveryEngine,
        ILogger<SourceDiscoveryJobExecutor> logger)
    {
        _linkRepository = linkRepository;
        _fetchItemRepository = fetchItemRepository;
        _context = context;
        _discoveryEngine = discoveryEngine;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var discoveryConfig = job.DiscoveryConfig ?? new DiscoveryConfig();
        var startedAt = DateTime.UtcNow;
        var maxDocsPerSource = FetchJobExecutor.ReadMaxDocsPerSource(job.Payload);

        _logger.LogInformation(
            "Starting discovery (source_discovery) for source {SourceId} with strategy {Strategy}, driver={Driver}, extraKeys=[{ExtraKeys}]",
            sourceId,
            discoveryConfig.Strategy ?? "unknown",
            discoveryConfig.Extra != null && discoveryConfig.Extra.TryGetValue("driver", out var d) ? d.GetString() : "(none)",
            discoveryConfig.Extra == null ? string.Empty : string.Join(",", discoveryConfig.Extra.Keys));
        if (maxDocsPerSource.HasValue)
        {
            _logger.LogInformation(
                "Discovery cap enabled for {SourceId}: max_docs_per_source={MaxDocs}",
                sourceId,
                maxDocsPerSource.Value);
        }

        progress.Report(new JobProgress
        {
            PercentComplete = 0,
            Message = "Iniciando descoberta...",
            Metrics = new Dictionary<string, object>()
        });

        var linksTotal = 0;
        var fetchItemsCreatedTotal = 0;
        var batchesPersisted = 0;
        var batch = new List<DiscoveredSource>(DiscoveryBatchSize);
        var discoveryRunEntity = new DiscoveryRunEntity
        {
            Id = Guid.NewGuid(),
            JobId = job.Id,
            SourceId = sourceId,
            StartedAt = startedAt,
            LinksTotal = 0,
            Status = "running"
        };
        _context.DiscoveryRuns.Add(discoveryRunEntity);
        await _context.SaveChangesAsync(ct);

        try
        {
            await foreach (var discovered in _discoveryEngine.DiscoverAsync(sourceId, discoveryConfig, ct))
            {
                batch.Add(discovered);
                linksTotal++;

                if (batch.Count >= DiscoveryBatchSize)
                {
                    fetchItemsCreatedTotal += await PersistBatchAsync(sourceId, batch, ct);
                    batchesPersisted++;
                    discoveryRunEntity.LinksTotal = linksTotal;
                    await _context.SaveChangesAsync(ct);
                    batch.Clear();

                    progress.Report(new JobProgress
                    {
                        PercentComplete = Math.Min(90, 30 + (batchesPersisted * 5)),
                        Message = $"Descobrindo... ({linksTotal} links, {batchesPersisted} lotes salvos)",
                        Metrics = new Dictionary<string, object> { ["linksFound"] = linksTotal, ["batchesPersisted"] = batchesPersisted }
                    });
                }

                if (maxDocsPerSource.HasValue && linksTotal >= maxDocsPerSource.Value)
                {
                    _logger.LogInformation(
                        "Discovery cap reached for {SourceId}: linksTotal={LinksTotal}, cap={MaxDocs}",
                        sourceId,
                        linksTotal,
                        maxDocsPerSource.Value);
                    break;
                }
            }

            if (batch.Count > 0)
            {
                fetchItemsCreatedTotal += await PersistBatchAsync(sourceId, batch, ct);
                batchesPersisted++;
                discoveryRunEntity.LinksTotal = linksTotal;
                await _context.SaveChangesAsync(ct);
                batch.Clear();
            }

            if (linksTotal == 0)
            {
                _logger.LogWarning(
                    "Discovery for source {SourceId} returned 0 links. Strategy={Strategy}. This may indicate an unimplemented strategy (web_crawl, api_pagination) or source configuration issue.",
                    sourceId, discoveryConfig.Strategy ?? "unknown");
            }

            if (linksTotal > 0 && fetchItemsCreatedTotal == 0)
            {
                var existingFetchItems = await _context.FetchItems.CountAsync(f => f.SourceId == sourceId, ct);
                if (existingFetchItems == 0)
                {
                    throw new InvalidOperationException(
                        $"Discovery persisted {linksTotal} links for source {sourceId}, but no fetch_items were materialized.");
                }
            }

            discoveryRunEntity.CompletedAt = DateTime.UtcNow;
            discoveryRunEntity.LinksTotal = linksTotal;
            discoveryRunEntity.Status = "completed";
            discoveryRunEntity.ErrorSummary = linksTotal == 0
                ? "0 links discovered (check strategy implementation)"
                : maxDocsPerSource.HasValue && linksTotal >= maxDocsPerSource.Value
                    ? $"capped at max_docs_per_source={maxDocsPerSource.Value}"
                    : null;
            await _context.SaveChangesAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Discovery job failed for source {SourceId} after {LinksTotal} links", sourceId, linksTotal);
            discoveryRunEntity.CompletedAt = DateTime.UtcNow;
            discoveryRunEntity.LinksTotal = linksTotal;
            discoveryRunEntity.Status = "failed";
            discoveryRunEntity.ErrorSummary = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message;
            await _context.SaveChangesAsync(ct);
            throw;
        }

        progress.Report(new JobProgress
        {
            PercentComplete = 100,
            Message = "Concluído",
            Metrics = new Dictionary<string, object> { ["linksFound"] = linksTotal, ["discoveryRunId"] = discoveryRunEntity.Id.ToString() }
        });

        _logger.LogInformation(
            "Discovery completed for source {SourceId}: {LinksTotal} links, status={Status}",
            sourceId, linksTotal, "completed");

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

    private async Task<int> PersistBatchAsync(string sourceId, List<DiscoveredSource> batch, CancellationToken ct)
    {
        if (batch.Count == 0)
            return 0;

        var linksToUpsert = batch.Select(d => new DiscoveredLinkEntity
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
            Metadata = d.Metadata is { Count: > 0 }
                ? System.Text.Json.JsonSerializer.Serialize(d.Metadata)
                : "{}"
        }).ToList();

        await _linkRepository.BulkUpsertAsync(linksToUpsert, ct);
        await _context.SaveChangesAsync(ct);

        var urlHashes = linksToUpsert.Select(l => l.UrlHash).ToList();
        var persistedLinks = await _context.DiscoveredLinks
            .Where(l => l.SourceId == sourceId && urlHashes.Contains(l.UrlHash))
            .ToListAsync(ct);
        var createdFetchItems = await _fetchItemRepository.EnsurePendingForLinksAsync(persistedLinks, ct);

        _logger.LogInformation(
            "Discovery batch materialization for {SourceId}: linksToUpsert={LinksToUpsert}, persistedLinks={PersistedLinks}, createdFetchItems={CreatedFetchItems}",
            sourceId, linksToUpsert.Count, persistedLinks.Count, createdFetchItems);

        return createdFetchItems;
    }
}
