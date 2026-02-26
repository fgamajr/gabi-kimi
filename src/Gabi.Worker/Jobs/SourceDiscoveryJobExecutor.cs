using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job executor for source_discovery jobs (enqueued by dashboard refresh).
/// Retry handled by Hangfire global policy (configured in Worker Hangfire:RetryPolicy).
/// Failsafe by default: 0 links from engine is success (LinksTotal=0) but logs warning.
/// In strict coverage mode (payload strict_coverage=true), 0 links or cap reach becomes inconclusive and job returns failure.
/// Persists links with DiscoveryStatus=completed, FetchStatus=IngestStatus=pending; records run in discovery_runs.
/// </summary>
public class SourceDiscoveryJobExecutor : IJobExecutor
{
    public string JobType => "source_discovery";
    private const int DiscoveryBatchSize = 1000;

    private readonly IDiscoveredLinkRepository _linkRepository;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly GabiDbContext _context;
    private readonly IJobQueueRepository _jobQueue;
    private readonly ILogger<SourceDiscoveryJobExecutor> _logger;
    private readonly DiscoveryEngine _discoveryEngine;

    public SourceDiscoveryJobExecutor(
        IDiscoveredLinkRepository linkRepository,
        IFetchItemRepository fetchItemRepository,
        GabiDbContext context,
        IJobQueueRepository jobQueue,
        DiscoveryEngine discoveryEngine,
        ILogger<SourceDiscoveryJobExecutor> logger)
    {
        _linkRepository = linkRepository;
        _fetchItemRepository = fetchItemRepository;
        _context = context;
        _jobQueue = jobQueue;
        _discoveryEngine = discoveryEngine;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var stageStopwatch = Stopwatch.StartNew();
        using var activity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.discovery", ActivityKind.Internal);
        activity?.SetTag("source.id", sourceId);
        var discoveryConfig = (job.DiscoveryConfig ?? new DiscoveryConfig()) with { SnapshotAt = DateTime.UtcNow };
        var startedAt = discoveryConfig.SnapshotAt!.Value;
        var maxDocsPerSource = FetchJobExecutor.ReadMaxDocsPerSource(job.Payload);
        var strictCoverage = FetchJobExecutor.ReadStrictCoverage(job.Payload);
        var zeroOk = FetchJobExecutor.ReadZeroOk(job.Payload);
        activity?.SetTag("coverage.strict", strictCoverage);
        activity?.SetTag("coverage.zero_ok", zeroOk);

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

        if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
        {
            _logger.LogInformation("Discovery skipped for {SourceId}: source is paused or stopped", sourceId);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object> { ["interrupted_by"] = "pause", ["links_total"] = 0 }
            };
        }

        var backpressure = PipelineBackpressureConfig.Load();
        var pendingFetch = await _fetchItemRepository.CountBySourceAndStatusesAsync(sourceId, new[] { "pending", "failed" }, ct);
        if (pendingFetch > backpressure.MaxPendingFetch)
        {
            _logger.LogInformation(
                "Discovery yielding for {SourceId}: backpressure pending_fetch={Pending} > {Max}",
                sourceId, pendingFetch, backpressure.MaxPendingFetch);
            var retryJob = new IngestJob
            {
                Id = Guid.NewGuid(),
                SourceId = sourceId,
                JobType = "source_discovery",
                Payload = job.Payload ?? new Dictionary<string, object>(),
                DiscoveryConfig = job.DiscoveryConfig
            };
            await _jobQueue.ScheduleAsync(retryJob, TimeSpan.FromSeconds(60), ct);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object>
                {
                    ["yielded"] = true,
                    ["reason"] = "backpressure",
                    ["pending_downstream"] = pendingFetch
                }
            };
        }

        // GEMINI-08: Read checkpoint from previous incomplete run and pass cursor to adapters.
        var checkpoint = await ReadDiscoveryCheckpointAsync(sourceId, ct);
        if (checkpoint.Count > 0)
        {
            var resumedLinks = checkpoint.TryGetValue("links_found", out var lf) ? lf : 0;
            _logger.LogInformation(
                "Resuming discovery for {SourceId} from checkpoint (links_found={LinksFound})",
                sourceId, resumedLinks);
            var extra = new Dictionary<string, JsonElement>(discoveryConfig.Extra ?? new Dictionary<string, JsonElement>());
            foreach (var (key, value) in checkpoint)
            {
                if (key == "links_found") continue;
                using var doc = JsonDocument.Parse(JsonSerializer.Serialize(value));
                extra[key] = doc.RootElement.Clone();
            }
            discoveryConfig = discoveryConfig with { Extra = extra };
        }

        var linksTotal = 0;
        var fetchItemsCreatedTotal = 0;
        var batchesPersisted = 0;
        var interruptedByPause = false;
        var batch = new List<DiscoveredSource>(DiscoveryBatchSize);
        var discoveredUrlsForHash = new List<string>();
        var cursor = new Dictionary<string, object>();
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
                if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
                {
                    _logger.LogInformation("Discovery interrupted for {SourceId}: source paused/stopped at {LinksTotal} links", sourceId, linksTotal);
                    interruptedByPause = true;
                    break;
                }

                batch.Add(discovered);
                discoveredUrlsForHash.Add(discovered.Url);
                UpdateCursorFromItem(discovered.Metadata, cursor);
                linksTotal++;

                if (batch.Count >= DiscoveryBatchSize)
                {
                    fetchItemsCreatedTotal += await PersistBatchAsync(sourceId, batch, ct);
                    batchesPersisted++;
                    discoveryRunEntity.LinksTotal = linksTotal;
                    await _context.SaveChangesAsync(ct);
                    batch.Clear();
                    await PersistDiscoveryCheckpointAsync(sourceId, linksTotal, cursor, ct);

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
                await PersistDiscoveryCheckpointAsync(sourceId, linksTotal, cursor, ct);
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

            var capReached = maxDocsPerSource.HasValue && linksTotal >= maxDocsPerSource.Value;
            var capValue = maxDocsPerSource.GetValueOrDefault();
            var zeroLinksInconclusive = linksTotal == 0 && !zeroOk;
            var cappedInconclusive = strictCoverage && capReached;

            var lastManifest = await _context.ExecutionManifests
                .Where(m => m.SourceId == sourceId && m.Status == "completed")
                .OrderByDescending(m => m.SnapshotAt)
                .FirstOrDefaultAsync(ct);
            int? expectedLinkCount = lastManifest?.ActualLinkCount;
            double? coverageRatio = expectedLinkCount.HasValue && expectedLinkCount.Value > 0
                ? (double)linksTotal / expectedLinkCount.Value
                : null;
            var minRatio = FetchJobExecutor.ReadMinCoverageRatio(job.Payload);
            var lowCoverageInconclusive = strictCoverage && coverageRatio.HasValue && coverageRatio.Value < minRatio && !zeroOk;

            var strictCoverageViolation = zeroLinksInconclusive || cappedInconclusive || lowCoverageInconclusive;
            var discoveryStatus = strictCoverageViolation ? "inconclusive" : "completed";
            var errorSummary = linksTotal == 0
                ? (zeroLinksInconclusive
                    ? "0 links discovered (strict_coverage=true)"
                    : "0 links discovered (check strategy implementation)")
                : capReached
                    ? (strictCoverage
                        ? $"capped at max_docs_per_source={capValue} (strict_coverage=true)"
                        : $"capped at max_docs_per_source={capValue}")
                    : lowCoverageInconclusive
                        ? $"coverage ratio {coverageRatio:F2} below min_coverage_ratio {minRatio:F2}"
                        : null;

            discoveryRunEntity.CompletedAt = DateTime.UtcNow;
            discoveryRunEntity.LinksTotal = linksTotal;
            discoveryRunEntity.Status = discoveryStatus;
            discoveryRunEntity.ErrorSummary = errorSummary;

            var externalIdSetHash = ComputeExternalIdSetHash(discoveredUrlsForHash);
            var manifest = new ExecutionManifestEntity
            {
                DiscoveryRunId = discoveryRunEntity.Id,
                SourceId = sourceId,
                SnapshotAt = startedAt,
                ResolvedParameters = JsonSerializer.Serialize(new
                {
                    snapshot_year = startedAt.Year,
                    source_id = sourceId,
                    strategy = discoveryConfig.Strategy ?? "unknown"
                }),
                ExpectedLinkCount = expectedLinkCount,
                ActualLinkCount = linksTotal,
                ExternalIdSetHash = externalIdSetHash,
                Status = discoveryStatus,
                CoverageRatio = coverageRatio.HasValue ? (decimal)coverageRatio.Value : null
            };
            _context.ExecutionManifests.Add(manifest);
            await _context.SaveChangesAsync(ct);

            // GEMINI-08: Clear checkpoint — this run completed (successfully or capped).
            await ClearDiscoveryCheckpointAsync(sourceId, ct);
        }
        catch (Exception ex)
        {
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            activity?.AddException(ex);
            activity?.SetTag("error.type", ex.GetType().Name);
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

        var inconclusive = discoveryRunEntity.Status == "inconclusive";
        var status = inconclusive ? JobTerminalStatus.Inconclusive : JobTerminalStatus.Success;
        _logger.LogInformation(
            "Discovery finished for source {SourceId}: links={LinksTotal}, strict_coverage={StrictCoverage}, zero_ok={ZeroOk}, status={Status}",
            sourceId, linksTotal, strictCoverage, zeroOk, status);
        if (inconclusive)
        {
            var strictErrorType = linksTotal == 0
                ? "strict_coverage_zero_links"
                : (discoveryRunEntity.ErrorSummary?.Contains("coverage ratio", StringComparison.OrdinalIgnoreCase) == true
                    ? "strict_coverage_low_ratio"
                    : "strict_coverage_capped");
            activity?.SetStatus(ActivityStatusCode.Error, strictErrorType);
            activity?.SetTag("error.type", strictErrorType);
        }

        activity?.SetTag("docs.count", linksTotal);
        PipelineTelemetry.RecordDocsProcessed(linksTotal, sourceId, "discovery");
        PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "discovery");

        var metadata = new Dictionary<string, object>
        {
            ["urls_discovered"] = linksTotal,
            ["source_id"] = sourceId,
            ["discovery_run_id"] = discoveryRunEntity.Id.ToString(),
            ["strict_coverage"] = strictCoverage,
            ["zero_ok"] = zeroOk
        };
        if (interruptedByPause)
        {
            metadata["interrupted_by"] = "pause";
            metadata["last_cursor"] = linksTotal;
        }
        return new JobResult { Status = status, Metadata = metadata };
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

    // ── GEMINI-08: Discovery checkpoint (cursor) helpers ─────────────────────

    /// <summary>Reads discovery_checkpoint from source_registry.PipelineConfig. Returns empty dict if none.</summary>
    private async Task<Dictionary<string, object>> ReadDiscoveryCheckpointAsync(string sourceId, CancellationToken ct)
    {
        var pipelineConfigJson = await _context.SourceRegistries
            .AsNoTracking()
            .Where(s => s.Id == sourceId)
            .Select(s => s.PipelineConfig)
            .FirstOrDefaultAsync(ct);

        if (string.IsNullOrWhiteSpace(pipelineConfigJson))
            return new Dictionary<string, object>();

        try
        {
            using var doc = JsonDocument.Parse(pipelineConfigJson);
            if (!doc.RootElement.TryGetProperty("discovery_checkpoint", out var checkpoint)
                || checkpoint.ValueKind != JsonValueKind.Object)
                return new Dictionary<string, object>();

            var result = new Dictionary<string, object>();
            foreach (var prop in checkpoint.EnumerateObject())
            {
                result[prop.Name] = prop.Value.ValueKind switch
                {
                    JsonValueKind.Number => prop.Value.TryGetInt32(out var i) ? (object)i : prop.Value.GetDouble(),
                    JsonValueKind.String => prop.Value.GetString() ?? string.Empty,
                    _ => prop.Value.Clone()
                };
            }
            return result;
        }
        catch
        {
            return new Dictionary<string, object>();
        }
    }

    /// <summary>Merges discovery_checkpoint into source_registry.PipelineConfig without overwriting other keys.</summary>
    private async Task PersistDiscoveryCheckpointAsync(string sourceId, int linksFound, Dictionary<string, object> cursor, CancellationToken ct)
    {
        if (cursor.Count == 0) return;

        var existing = await _context.SourceRegistries
            .AsNoTracking()
            .Where(s => s.Id == sourceId)
            .Select(s => s.PipelineConfig)
            .FirstOrDefaultAsync(ct);

        var pipelineConfig = new Dictionary<string, JsonElement>();
        if (!string.IsNullOrWhiteSpace(existing))
        {
            try
            {
                using var existingDoc = JsonDocument.Parse(existing);
                foreach (var prop in existingDoc.RootElement.EnumerateObject())
                    pipelineConfig[prop.Name] = prop.Value.Clone();
            }
            catch { }
        }

        var checkpointPayload = new Dictionary<string, object>(cursor) { ["links_found"] = linksFound };
        var checkpointJson = JsonSerializer.Serialize(checkpointPayload);
        using var checkpointDoc = JsonDocument.Parse(checkpointJson);
        pipelineConfig["discovery_checkpoint"] = checkpointDoc.RootElement.Clone();

        var newJson = JsonSerializer.Serialize(pipelineConfig);
        await _context.SourceRegistries
            .Where(s => s.Id == sourceId)
            .ExecuteUpdateAsync(s => s.SetProperty(r => r.PipelineConfig, newJson), ct);
    }

    /// <summary>Removes discovery_checkpoint from source_registry.PipelineConfig after successful completion.</summary>
    private async Task ClearDiscoveryCheckpointAsync(string sourceId, CancellationToken ct)
    {
        var existing = await _context.SourceRegistries
            .AsNoTracking()
            .Where(s => s.Id == sourceId)
            .Select(s => s.PipelineConfig)
            .FirstOrDefaultAsync(ct);

        if (string.IsNullOrWhiteSpace(existing)) return;

        try
        {
            var pipelineConfig = new Dictionary<string, JsonElement>();
            using var doc = JsonDocument.Parse(existing);
            foreach (var prop in doc.RootElement.EnumerateObject())
            {
                if (prop.Name != "discovery_checkpoint")
                    pipelineConfig[prop.Name] = prop.Value.Clone();
            }
            var newJson = pipelineConfig.Count == 0 ? null : JsonSerializer.Serialize(pipelineConfig);
            await _context.SourceRegistries
                .Where(s => s.Id == sourceId)
                .ExecuteUpdateAsync(s => s.SetProperty(r => r.PipelineConfig, newJson), ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to clear discovery checkpoint for {SourceId}", sourceId);
        }
    }

    /// <summary>Extracts adapter-specific cursor position from a discovered item's metadata.</summary>
    private static void UpdateCursorFromItem(IReadOnlyDictionary<string, object>? metadata, Dictionary<string, object> cursor)
    {
        if (metadata == null) return;
        var driver = metadata.TryGetValue("driver", out var d) ? d?.ToString() : null;
        switch (driver)
        {
            case "btcu_api_v1":
                if (metadata.TryGetValue("api_page", out var page)) cursor["resume_btcu_page"] = page;
                break;
            case "camara_api_v1":
                if (metadata.TryGetValue("year", out var cy)) cursor["resume_camara_year"] = cy;
                break;
            case "senado_legislacao_api_v1":
                if (metadata.TryGetValue("year", out var sy)) cursor["resume_senado_year"] = sy;
                break;
            case "dou_inlabs_xml_v1":
                if (metadata.TryGetValue("data_publicacao", out var dp)) cursor["resume_dou_date"] = dp;
                break;
            case "dou_monthly_pattern_v1":
                if (metadata.TryGetValue("year", out var dy)) cursor["resume_dou_year"] = dy;
                if (metadata.TryGetValue("month", out var dm)) cursor["resume_dou_month"] = dm;
                break;
        }
    }

    private static string ComputeExternalIdSetHash(List<string> urls)
    {
        if (urls.Count == 0)
            return Convert.ToHexString(SHA256.HashData(Array.Empty<byte>())).ToLowerInvariant();
        var sorted = urls.Distinct(StringComparer.Ordinal).OrderBy(u => u, StringComparer.Ordinal).ToList();
        var payload = string.Join("\n", sorted);
        var bytes = Encoding.UTF8.GetBytes(payload);
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
