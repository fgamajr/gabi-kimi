// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Text.Json;
using System.Diagnostics;
using Gabi.Contracts.Api;
using Gabi.Contracts.Common;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Api.Services;

/// <summary>
/// Service that aggregates dashboard data from PostgreSQL, Elasticsearch, and Job Queue.
/// Provides data in the exact format expected by the React frontend.
/// </summary>
public interface IDashboardService
{
    Task<DashboardStatsResponse> GetStatsAsync(CancellationToken ct = default);
    Task<JobsResponse> GetJobsAsync(CancellationToken ct = default);
    Task<IReadOnlyList<PipelineStage>> GetPipelineAsync(CancellationToken ct = default);
    Task<SystemHealthResponse> GetSystemHealthAsync(CancellationToken ct = default);
    Task<RefreshSourceResponse> RefreshSourceAsync(string sourceId, RefreshSourceRequest request, CancellationToken ct = default);
    /// <summary>Enfileira job de seed (catalog_seed). O Worker persiste o YAML no banco com retry e registra em seed_runs.</summary>
    Task<SeedResponse> SeedSourcesAsync(CancellationToken ct = default);
    /// <summary>Última execução do seed (para a fase de discovery saber se o catálogo está pronto).</summary>
    Task<SeedRunDto?> GetLastSeedRunAsync(CancellationToken ct = default);

    /// <summary>Última execução de discovery para uma fonte (ou última global se sourceId for null).</summary>
    Task<DiscoveryRunDto?> GetLastDiscoveryRunAsync(string? sourceId, CancellationToken ct = default);
    /// <summary>Última execução de fetch para uma fonte (ou última global se sourceId for null).</summary>
    Task<FetchRunDto?> GetLastFetchRunAsync(string? sourceId, CancellationToken ct = default);

    /// <summary>
    /// Obtém detalhes completos de uma source com estatísticas.
    /// </summary>
    Task<SourceDetailsResponse> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Lista links paginados de uma source.
    /// </summary>
    Task<LinkListResponse> GetLinksAsync(string sourceId, LinkListRequest request, CancellationToken ct = default);

    /// <summary>
    /// Obtém detalhes de um link específico.
    /// </summary>
    Task<DiscoveredLinkDetailDto?> GetLinkByIdAsync(string sourceId, long linkId, CancellationToken ct = default);

    /// <summary>
    /// Obtém detalhamento por safra (ano) para uma source.
    /// </summary>
    Task<SafraResponse> GetSafraAsync(string? sourceId, CancellationToken ct = default);

    /// <summary>
    /// Inicia uma fase do pipeline para uma source (discovery, fetch, ingest). Retorna job enfileirado.
    /// </summary>
    Task<RefreshSourceResponse> StartPhaseAsync(string sourceId, string phase, StartPhaseRequest? request = null, CancellationToken ct = default);
    Task<RefreshSourceResponse> RunPipelineAsync(string sourceId, StartPhaseRequest? request = null, CancellationToken ct = default);

    /// <summary>
    /// Lista fases do pipeline com disponibilidade e como disparar (para o frontend).
    /// </summary>
    Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default);

    /// <summary>
    /// Reindex: marca documentos ativos (completed/completed_metadata_only) da fonte como pending e enfileira um job de ingest.
    /// Retorna quantidade de documentos enfileirados para re-ingest e source_id.
    /// </summary>
    Task<ReindexSourceResponse?> ReindexSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>Gets pipeline state for a source (idle, running, paused, failed).</summary>
    Task<SourcePipelineStateDto?> GetSourcePipelineStateAsync(string sourceId, CancellationToken ct = default);

    /// <summary>Pauses the pipeline for a source (running jobs will exit gracefully on next check).</summary>
    Task<RefreshSourceResponse> PauseSourceAsync(string sourceId, string? pausedBy = null, CancellationToken ct = default);

    /// <summary>Resumes the pipeline and optionally re-enqueues the active phase.</summary>
    Task<RefreshSourceResponse> ResumeSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>Stops the pipeline for a source (sets state to idle).</summary>
    Task<RefreshSourceResponse> StopSourceAsync(string sourceId, CancellationToken ct = default);
}

public class DashboardService : IDashboardService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DashboardService> _logger;
    private readonly ISourceCatalog _sourceCatalog;
    private readonly ISystemHealthService _systemHealthService;
    private readonly ISourceControlService _sourceControlService;
    private readonly IPipelineStatsService _pipelineStatsService;
    private readonly ISourceQueryService _sourceQueryService;

    public DashboardService(
        IServiceProvider serviceProvider,
        ILogger<DashboardService> logger,
        IConfiguration configuration,
        ISourceCatalog sourceCatalog,
        ISystemHealthService systemHealthService,
        ISourceControlService sourceControlService,
        IPipelineStatsService pipelineStatsService,
        ISourceQueryService sourceQueryService)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _sourceCatalog = sourceCatalog;
        _systemHealthService = systemHealthService;
        _sourceControlService = sourceControlService;
        _pipelineStatsService = pipelineStatsService;
        _sourceQueryService = sourceQueryService;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Group A — Pipeline stats/query (delegated to PipelineStatsService)
    // ═══════════════════════════════════════════════════════════════════════════

    public Task<SeedRunDto?> GetLastSeedRunAsync(CancellationToken ct = default)
        => _pipelineStatsService.GetLastSeedRunAsync(ct);

    public Task<DiscoveryRunDto?> GetLastDiscoveryRunAsync(string? sourceId, CancellationToken ct = default)
        => _pipelineStatsService.GetLastDiscoveryRunAsync(sourceId, ct);

    public Task<FetchRunDto?> GetLastFetchRunAsync(string? sourceId, CancellationToken ct = default)
        => _pipelineStatsService.GetLastFetchRunAsync(sourceId, ct);

    public Task<DashboardStatsResponse> GetStatsAsync(CancellationToken ct = default)
        => _pipelineStatsService.GetStatsAsync(ct);

    public Task<JobsResponse> GetJobsAsync(CancellationToken ct = default)
        => _pipelineStatsService.GetJobsAsync(ct);

    public Task<IReadOnlyList<PipelineStage>> GetPipelineAsync(CancellationToken ct = default)
        => _pipelineStatsService.GetPipelineAsync(ct);

    public Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default)
        => _pipelineStatsService.GetPipelinePhasesAsync(ct);

    public Task<SourcePipelineStateDto?> GetSourcePipelineStateAsync(string sourceId, CancellationToken ct = default)
        => _pipelineStatsService.GetSourcePipelineStateAsync(sourceId, ct);

    // ═══════════════════════════════════════════════════════════════════════════
    // Group B — Source/link queries (delegated to SourceQueryService)
    // ═══════════════════════════════════════════════════════════════════════════

    public Task<SourceDetailsResponse> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default)
        => _sourceQueryService.GetSourceDetailsAsync(sourceId, ct);

    public Task<LinkListResponse> GetLinksAsync(string sourceId, LinkListRequest request, CancellationToken ct = default)
        => _sourceQueryService.GetLinksAsync(sourceId, request, ct);

    public Task<DiscoveredLinkDetailDto?> GetLinkByIdAsync(string sourceId, long linkId, CancellationToken ct = default)
        => _sourceQueryService.GetLinkByIdAsync(sourceId, linkId, ct);

    public Task<SafraResponse> GetSafraAsync(string? sourceId, CancellationToken ct = default)
        => _sourceQueryService.GetSafraAsync(sourceId, ct);

    // ═══════════════════════════════════════════════════════════════════════════
    // Previously extracted services (health + source control)
    // ═══════════════════════════════════════════════════════════════════════════

    public Task<SystemHealthResponse> GetSystemHealthAsync(CancellationToken ct = default)
        => _systemHealthService.GetSystemHealthAsync(ct);

    public Task<RefreshSourceResponse> PauseSourceAsync(string sourceId, string? pausedBy = null, CancellationToken ct = default)
        => _sourceControlService.PauseSourceAsync(sourceId, pausedBy, ct);

    public Task<RefreshSourceResponse> ResumeSourceAsync(string sourceId, CancellationToken ct = default)
        => _sourceControlService.ResumeSourceAsync(sourceId, ct);

    public Task<RefreshSourceResponse> StopSourceAsync(string sourceId, CancellationToken ct = default)
        => _sourceControlService.StopSourceAsync(sourceId, ct);

    // ═══════════════════════════════════════════════════════════════════════════
    // Group C — Pipeline operations (kept inline: complex orchestration)
    // ═══════════════════════════════════════════════════════════════════════════

    public async Task<SeedResponse> SeedSourcesAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        var latest = await jobQueue.GetLatestByJobTypeAsync("catalog_seed", ct);
        if (latest?.Status is JobStatus.Running or JobStatus.Pending)
        {
            return new SeedResponse
            {
                Success = true,
                JobId = latest.Id,
                Message = "Seed already in progress. Poll GET /api/v1/dashboard/seed/last for status."
            };
        }

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "catalog_seed",
            SourceId = string.Empty,
            Payload = BuildTraceContextPayload(new Dictionary<string, object>
            {
                ["run_id"] = Guid.NewGuid().ToString()
            }),
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 3
        };
        var jobId = await jobQueue.EnqueueAsync(job, ct);
        _logger.LogInformation("Enqueued catalog_seed job {JobId}", jobId);
        return new SeedResponse
        {
            Success = true,
            JobId = jobId,
            Message = "Seed job enqueued. Worker will load sources from YAML, persist with retry, and register in seed_runs. Poll GET /api/v1/dashboard/seed/last for result."
        };
    }

    public async Task<RefreshSourceResponse> RefreshSourceAsync(string sourceId, RefreshSourceRequest request, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        // Verify source exists
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
        {
            return new RefreshSourceResponse
            {
                Success = false,
                Message = $"Source not found: {sourceId}"
            };
        }

        // Check if there's already a running job
        var latestJob = await jobQueue.GetLatestForSourceAsync(sourceId, ct);
        if (latestJob?.Status is JobStatus.Running or JobStatus.Pending)
        {
            return new RefreshSourceResponse
            {
                Success = true,
                JobId = latestJob.Id,
                Message = $"Job already in progress for {sourceId}"
            };
        }

        // Create and enqueue the job
        var strictCoverage = ResolveStrictCoverage(request.StrictCoverage, source.PipelineConfig);
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = sourceId,
            Payload = BuildTraceContextPayload(new Dictionary<string, object>
            {
                ["force"] = request.Force,
                ["year"] = request.Year,
                ["discoveryConfig"] = source.DiscoveryConfig
            }),
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow
        };
        if (request.MaxDocsPerSource is int maxDocsPerSource && maxDocsPerSource > 0)
            job.Payload["max_docs_per_source"] = maxDocsPerSource;
        if (strictCoverage)
            job.Payload["strict_coverage"] = true;
        if (request.ChainNext == true)
            job.Payload["chain_next"] = true;
        var zeroOk = ReadZeroOkFromPipelineConfig(source.PipelineConfig);
        if (zeroOk)
            job.Payload["zero_ok"] = true;

        var jobId = await jobQueue.EnqueueAsync(job, ct);

        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var pipelineState = await db.SourcePipelineStates.FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        var now = DateTime.UtcNow;
        if (pipelineState == null)
        {
            db.SourcePipelineStates.Add(new SourcePipelineStateEntity
            {
                SourceId = sourceId,
                State = Status.Running,
                ActivePhase = "discovery",
                LastResumedAt = now,
                UpdatedAt = now
            });
        }
        else
        {
            pipelineState.State = Status.Running;
            pipelineState.ActivePhase = "discovery";
            pipelineState.LastResumedAt = now;
            pipelineState.UpdatedAt = now;
        }
        await db.SaveChangesAsync(ct);

        _logger.LogInformation("Enqueued refresh job {JobId} for source {SourceId}", jobId, sourceId);

        return new RefreshSourceResponse
        {
            Success = true,
            JobId = jobId,
            Message = $"Refresh queued for {sourceId}"
        };
    }

    public async Task<RefreshSourceResponse> StartPhaseAsync(string sourceId, string phase, StartPhaseRequest? request = null, CancellationToken ct = default)
    {
        var normalized = phase?.ToLowerInvariant().Trim() ?? "";
        if (normalized == "discovery")
        {
            return await RefreshSourceAsync(
                sourceId,
                new RefreshSourceRequest
                {
                    Force = true,
                    MaxDocsPerSource = request?.MaxDocsPerSource,
                    StrictCoverage = request?.StrictCoverage,
                    ChainNext = request?.ChainNext
                },
                ct);
        }

        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
        {
            return new RefreshSourceResponse { Success = false, Message = $"Source not found: {sourceId}" };
        }

        var latestJob = await jobQueue.GetLatestForSourceAsync(sourceId, ct);
        if (latestJob?.Status is JobStatus.Running or JobStatus.Pending)
        {
            return new RefreshSourceResponse
            {
                Success = true,
                JobId = latestJob.Id,
                Message = $"Job already in progress for {sourceId}"
            };
        }

        string jobType = normalized switch
        {
            "fetch" => "fetch",
            "ingest" => "ingest",
            _ => throw new ArgumentException($"Unknown phase: {phase}. Use discovery, fetch, or ingest.", nameof(phase))
        };

        var payload = BuildTraceContextPayload(new Dictionary<string, object> { ["phase"] = normalized });
        var strictCoverage = ResolveStrictCoverage(request?.StrictCoverage, source.PipelineConfig);
        if (normalized == "fetch" && request?.MaxDocsPerSource is int maxDocsPerSource && maxDocsPerSource > 0)
        {
            payload["max_docs_per_source"] = maxDocsPerSource;
        }
        if (strictCoverage)
            payload["strict_coverage"] = true;
        if (request?.ChainNext == true)
            payload["chain_next"] = true;

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = jobType,
            SourceId = sourceId,
            Payload = payload,
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            IdempotencyKey = Guid.NewGuid().ToString()
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);
        _logger.LogInformation("Enqueued {Phase} job {JobId} for source {SourceId}", normalized, jobId, sourceId);

        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var pipelineState = await db.SourcePipelineStates.FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        var now = DateTime.UtcNow;
        if (pipelineState == null)
        {
            db.SourcePipelineStates.Add(new SourcePipelineStateEntity
            {
                SourceId = sourceId,
                State = Status.Running,
                ActivePhase = normalized,
                LastResumedAt = now,
                UpdatedAt = now
            });
        }
        else
        {
            pipelineState.State = Status.Running;
            pipelineState.ActivePhase = normalized;
            pipelineState.LastResumedAt = now;
            pipelineState.UpdatedAt = now;
        }
        await db.SaveChangesAsync(ct);

        return new RefreshSourceResponse
        {
            Success = true,
            JobId = jobId,
            Message = $"{normalized} queued for {sourceId}"
        };
    }

    public Task<RefreshSourceResponse> RunPipelineAsync(string sourceId, StartPhaseRequest? request = null, CancellationToken ct = default)
    {
        var pipelineRequest = request is null
            ? new StartPhaseRequest { ChainNext = true }
            : request with { ChainNext = true };
        return StartPhaseAsync(sourceId, "discovery", pipelineRequest, ct);
    }

    public async Task<ReindexSourceResponse?> ReindexSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            return null;

        var latestJob = await jobQueue.GetLatestForSourceAsync(sourceId, ct);
        if (latestJob?.Status is JobStatus.Running or JobStatus.Pending)
        {
            _logger.LogInformation("Reindex skipped for {SourceId}: ingest job already in progress", sourceId);
            return new ReindexSourceResponse { Queued = 0, SourceId = sourceId };
        }

        var activeStatuses = new[] { "completed", "completed_metadata_only" };
        var count = await db.Documents
            .Where(d => d.SourceId == sourceId && activeStatuses.Contains(d.Status) && d.RemovedFromSourceAt == null)
            .CountAsync(ct);
        if (count == 0)
            return new ReindexSourceResponse { Queued = 0, SourceId = sourceId };

        await db.Documents
            .Where(d => d.SourceId == sourceId && activeStatuses.Contains(d.Status) && d.RemovedFromSourceAt == null)
            .ExecuteUpdateAsync(s => s.SetProperty(d => d.Status, "pending"), ct);

        var payload = BuildTraceContextPayload(new Dictionary<string, object> { ["phase"] = "ingest" });
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "ingest",
            SourceId = sourceId,
            Payload = payload,
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            IdempotencyKey = Guid.NewGuid().ToString()
        };
        await jobQueue.EnqueueAsync(job, ct);
        _logger.LogInformation("Reindex enqueued for {SourceId}: {Count} documents set to pending, ingest job enqueued", sourceId, count);
        return new ReindexSourceResponse { Queued = count, SourceId = sourceId };
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Private Helpers (Group C — pipeline operations)
    // ═══════════════════════════════════════════════════════════════════════════

    private static Dictionary<string, object> BuildTraceContextPayload(Dictionary<string, object> payload)
    {
        var traceParent = Activity.Current?.Id;
        var traceId = Activity.Current?.TraceId.ToString();

        if (!string.IsNullOrWhiteSpace(traceParent))
            payload["traceparent"] = traceParent;

        if (!string.IsNullOrWhiteSpace(traceId))
            payload["trace_id"] = traceId!;

        if (!payload.ContainsKey("request_id"))
            payload["request_id"] = traceId ?? Guid.NewGuid().ToString("N");

        return payload;
    }

    private static bool ResolveStrictCoverage(bool? requestedStrictCoverage, string? pipelineConfigJson)
    {
        if (requestedStrictCoverage.HasValue)
            return requestedStrictCoverage.Value;

        return ReadStrictCoverageFromPipelineConfig(pipelineConfigJson);
    }

    private static bool ReadStrictCoverageFromPipelineConfig(string? pipelineConfigJson)
    {
        if (string.IsNullOrWhiteSpace(pipelineConfigJson))
            return false;

        try
        {
            using var json = JsonDocument.Parse(pipelineConfigJson);
            var root = json.RootElement;

            if (TryGetPropertyIgnoreCase(root, "strict_coverage", out var strictCoverageElement) &&
                TryReadBoolean(strictCoverageElement, out var strictCoverage))
                return strictCoverage;

            if (TryGetPropertyIgnoreCase(root, "coverage", out var coverageElement) &&
                TryGetPropertyIgnoreCase(coverageElement, "strict", out var strictElement) &&
                TryReadBoolean(strictElement, out var strictFromCoverage))
                return strictFromCoverage;
        }
        catch (JsonException)
        {
            // Keep fail-open behavior for dashboard triggering when pipeline config JSON is malformed.
            return false;
        }

        return false;
    }

    private static bool ReadZeroOkFromPipelineConfig(string? pipelineConfigJson)
    {
        if (string.IsNullOrWhiteSpace(pipelineConfigJson))
            return false;

        try
        {
            using var json = JsonDocument.Parse(pipelineConfigJson);
            var root = json.RootElement;

            if (TryGetPropertyIgnoreCase(root, "coverage", out var coverageElement) &&
                TryGetPropertyIgnoreCase(coverageElement, "zero_ok", out var zeroOkElement) &&
                TryReadBoolean(zeroOkElement, out var zeroOk))
                return zeroOk;
        }
        catch (JsonException)
        {
            return false;
        }

        return false;
    }

    private static bool TryGetPropertyIgnoreCase(JsonElement element, string propertyName, out JsonElement value)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (string.Equals(property.Name, propertyName, StringComparison.OrdinalIgnoreCase))
                {
                    value = property.Value;
                    return true;
                }
            }
        }

        value = default;
        return false;
    }

    private static bool TryReadBoolean(JsonElement element, out bool value)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.True:
                value = true;
                return true;
            case JsonValueKind.False:
                value = false;
                return true;
            case JsonValueKind.Number when element.TryGetInt32(out var numeric):
                value = numeric != 0;
                return true;
            case JsonValueKind.String:
            {
                var raw = element.GetString();
                if (bool.TryParse(raw, out var boolValue))
                {
                    value = boolValue;
                    return true;
                }

                if (int.TryParse(raw, out var numericValue))
                {
                    value = numericValue != 0;
                    return true;
                }

                break;
            }
        }

        value = false;
        return false;
    }
}
