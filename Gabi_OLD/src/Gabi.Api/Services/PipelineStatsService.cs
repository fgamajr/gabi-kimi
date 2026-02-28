// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Api.Services;

/// <summary>
/// Provides pipeline statistics and run queries (seed, discovery, fetch, jobs, pipeline state).
/// </summary>
public interface IPipelineStatsService
{
    Task<SeedRunDto?> GetLastSeedRunAsync(CancellationToken ct = default);
    Task<DiscoveryRunDto?> GetLastDiscoveryRunAsync(string? sourceId, CancellationToken ct = default);
    Task<FetchRunDto?> GetLastFetchRunAsync(string? sourceId, CancellationToken ct = default);
    Task<DashboardStatsResponse> GetStatsAsync(CancellationToken ct = default);
    Task<JobsResponse> GetJobsAsync(CancellationToken ct = default);
    Task<IReadOnlyList<PipelineStage>> GetPipelineAsync(CancellationToken ct = default);
    Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default);
    Task<SourcePipelineStateDto?> GetSourcePipelineStateAsync(string sourceId, CancellationToken ct = default);
}

public class PipelineStatsService : IPipelineStatsService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<PipelineStatsService> _logger;
    private readonly IConfiguration _configuration;

    public PipelineStatsService(
        IServiceProvider serviceProvider,
        ILogger<PipelineStatsService> logger,
        IConfiguration configuration)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<SeedRunDto?> GetLastSeedRunAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var last = await context.SeedRuns
            .OrderByDescending(r => r.StartedAt)
            .AsNoTracking()
            .FirstOrDefaultAsync(ct);
        if (last == null) return null;
        return new SeedRunDto
        {
            Id = last.Id,
            JobId = last.JobId,
            CompletedAt = last.CompletedAt,
            SourcesTotal = last.SourcesTotal,
            SourcesSeeded = last.SourcesSeeded,
            SourcesFailed = last.SourcesFailed,
            Status = last.Status,
            ErrorSummary = last.ErrorSummary
        };
    }

    public async Task<DiscoveryRunDto?> GetLastDiscoveryRunAsync(string? sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        IQueryable<DiscoveryRunEntity> query = context.DiscoveryRuns.AsNoTracking();
        if (!string.IsNullOrEmpty(sourceId))
            query = query.Where(r => r.SourceId == sourceId);
        var last = await query.OrderByDescending(r => r.CompletedAt).FirstOrDefaultAsync(ct);
        if (last == null) return null;
        return new DiscoveryRunDto
        {
            Id = last.Id,
            JobId = last.JobId,
            SourceId = last.SourceId,
            CompletedAt = last.CompletedAt,
            LinksTotal = last.LinksTotal,
            Status = last.Status,
            ErrorSummary = last.ErrorSummary
        };
    }

    public async Task<FetchRunDto?> GetLastFetchRunAsync(string? sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        IQueryable<FetchRunEntity> query = context.FetchRuns.AsNoTracking();
        if (!string.IsNullOrEmpty(sourceId))
            query = query.Where(r => r.SourceId == sourceId);
        var last = await query.OrderByDescending(r => r.CompletedAt).FirstOrDefaultAsync(ct);
        if (last == null) return null;
        return new FetchRunDto
        {
            Id = last.Id,
            JobId = last.JobId,
            SourceId = last.SourceId,
            CompletedAt = last.CompletedAt,
            ItemsTotal = last.ItemsTotal,
            ItemsCompleted = last.ItemsCompleted,
            ItemsFailed = last.ItemsFailed,
            Status = last.Status,
            ErrorSummary = last.ErrorSummary
        };
    }

    public async Task<DashboardStatsResponse> GetStatsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var sources = await sourceRepo.GetAllAsync(ct);
        var sourceList = new List<DashboardSource>();
        var totalDocuments = 0;

        var sourceIds = sources.Select(s => s.Id).ToList();
        var allLinks = await linkRepo.GetBySourcesAsync(sourceIds, ct);
        var linkCountBySource = allLinks
            .GroupBy(l => l.SourceId)
            .ToDictionary(g => g.Key, g => g.Count());

        foreach (var s in sources)
        {
            var docCount = linkCountBySource.GetValueOrDefault(s.Id, 0);
            totalDocuments += docCount;

            sourceList.Add(new DashboardSource
            {
                Id = s.Id,
                Description = s.Description ?? s.Name,
                SourceType = NormalizeSourceType(s.DiscoveryStrategy),
                Enabled = s.Enabled,
                DocumentCount = docCount
            });
        }

        // Get Job Stats for SyncStatus
        var jobStats = new JobQueueStatistics();
        try
        {
            var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
            jobStats = await jobQueue.GetStatisticsAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get job queue statistics");
        }

        return new DashboardStatsResponse
        {
            Sources = sourceList,
            TotalDocuments = totalDocuments,
            ElasticsearchAvailable = await CheckElasticsearchAsync(),

            // Extended Stats (Stubs + Real Data)
            SyncStatus = new SyncStatusDto
            {
                SyncedCount = totalDocuments, // Approximation
                ProcessingCount = jobStats.RunningCount + jobStats.PendingCount,
                TotalCount = totalDocuments + jobStats.RunningCount + jobStats.PendingCount
            },
            Throughput = new ThroughputDto
            {
                DocsPerMin = 9807.6, // Stub based on visual
                EtaMinutes = 5
            },
            RagStats = new RagStatsDto
            {
                IndexedCount = (int)(totalDocuments * 0.61), // Stub: 61% indexed
                IndexedPercentage = 61.0,
                VectorChunksCount = totalDocuments * 3, // Stub: 3 chunks per doc
                IndexSizeMb = 127.0 // Stub
            }
        };
    }

    public async Task<JobsResponse> GetJobsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();

        // Get recent jobs from the queue
        var jobs = await jobQueue.GetRecentJobsAsync(50, ct);
        var syncJobs = new List<SyncJob>();

        // Get all sources for mapping
        var sources = await sourceRepo.GetAllAsync(ct);
        var sourceDict = sources.ToDictionary(s => s.Id);

        foreach (var job in jobs)
        {
            // Map job status to SyncJobStatus
            var status = job.Status switch
            {
                JobStatus.Completed => SyncJobStatus.Synced,
                JobStatus.Pending => SyncJobStatus.Pending,
                JobStatus.Failed => SyncJobStatus.Failed,
                JobStatus.Running => SyncJobStatus.InProgress,
                _ => SyncJobStatus.Pending
            };

            // Extract year from payload if available
            var year = ExtractYearFromJob(job);

            syncJobs.Add(new SyncJob
            {
                Source = job.SourceId,
                Year = year,
                Status = status,
                UpdatedAt = (job.CompletedAt ?? job.StartedAt ?? job.CreatedAt).ToString("O")
            });
        }

        // Mock Elasticsearch indexes data for now
        var elasticIndexes = new Dictionary<string, int>();
        foreach (var source in sources.Take(5))
        {
            elasticIndexes[$"gabi_{source.Id.ToLowerInvariant()}"] = new Random().Next(100, 10000);
        }

        return new JobsResponse
        {
            SyncJobs = syncJobs,
            ElasticIndexes = elasticIndexes,
            TotalElasticDocs = elasticIndexes.Values.Sum()
        };
    }

    public async Task<IReadOnlyList<PipelineStage>> GetPipelineAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var stats = await jobQueue.GetStatisticsAsync(ct);
        var totalLinks = await linkRepo.GetTotalCountAsync(ct);
        var isActive = stats.RunningCount > 0;

        return new List<PipelineStage>
        {
            new()
            {
                Name = PipelineStageName.Discovery,
                Label = "Discovery",
                Description = "URL discovery from sources",
                Count = totalLinks,
                Total = Math.Max(totalLinks, 1),
                Status = isActive ? PipelineStageStatus.Active : PipelineStageStatus.Idle,
                Availability = "available",
                LastActivity = DateTime.UtcNow.ToString("O")
            },
            new()
            {
                Name = PipelineStageName.Ingest,
                Label = "Ingest",
                Description = "Document extraction and storage",
                Count = 0,
                Total = totalLinks,
                Status = PipelineStageStatus.Idle,
                Availability = "available",
                LastActivity = null
            },
            new()
            {
                Name = PipelineStageName.Processing,
                Label = "Processing",
                Description = "Text extraction and chunking",
                Count = 0,
                Total = totalLinks,
                Status = PipelineStageStatus.Idle,
                Availability = "available",
                LastActivity = null
            },
            new()
            {
                Name = PipelineStageName.Embedding,
                Label = "Embedding",
                Description = "Vector embedding generation",
                Count = 0,
                Total = totalLinks,
                Status = PipelineStageStatus.Idle,
                Availability = "available",
                LastActivity = null
            },
            new()
            {
                Name = PipelineStageName.Indexing,
                Label = "Indexing",
                Description = "Elasticsearch indexing",
                Count = 0,
                Total = totalLinks,
                Status = PipelineStageStatus.Idle,
                Availability = "available",
                LastActivity = null
            }
        };
    }

    public Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default)
    {
        var phases = new List<PipelinePhaseDto>
        {
            new() { Id = "seed", Name = "Seed", Description = "Carregar fontes do YAML no banco", Availability = "available", TriggerEndpoint = "POST /api/v1/dashboard/seed" },
            new() { Id = "discovery", Name = "Discovery", Description = "Descobrir URLs das fontes", Availability = "available", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/phases/discovery" },
            new() { Id = "fetch", Name = "Fetch", Description = "Baixar conteúdo dos links descobertos", Availability = "requires_previous", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/phases/fetch" },
            new() { Id = "ingest", Name = "Ingest", Description = "Processar e indexar documentos", Availability = "requires_previous", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/phases/ingest" }
        };
        return Task.FromResult<IReadOnlyList<PipelinePhaseDto>>(phases);
    }

    public async Task<SourcePipelineStateDto?> GetSourcePipelineStateAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var state = await db.SourcePipelineStates.AsNoTracking()
            .FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        if (state == null)
            return null;
        return new SourcePipelineStateDto
        {
            SourceId = state.SourceId,
            State = state.State,
            ActivePhase = state.ActivePhase,
            PausedAt = state.PausedAt,
            LastResumedAt = state.LastResumedAt,
            UpdatedAt = state.UpdatedAt
        };
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Private Helpers
    // ═══════════════════════════════════════════════════════════════════════════

    private static string NormalizeSourceType(string? discoveryStrategy)
    {
        return discoveryStrategy?.ToLowerInvariant() switch
        {
            "static_url" => "csv_http",
            "url_pattern" => "csv_http",
            "web_crawl" => "web_crawl",
            "api_pagination" => "api_pagination",
            _ => "unknown"
        };
    }

    private static object ExtractYearFromJob(IngestJob job)
    {
        // Try to get year from payload
        if (job.Payload != null && job.Payload.TryGetValue("year", out var yearValue))
        {
            if (yearValue is int yearInt)
                return yearInt;
            if (yearValue is string yearStr && int.TryParse(yearStr, out var parsedYear))
                return parsedYear;
        }

        // Extract year from SourceId or default to current year
        var parts = job.SourceId.Split('_');
        if (parts.Length > 1 && int.TryParse(parts[^1], out var sourceYear))
            return sourceYear;

        return DateTime.UtcNow.Year;
    }

    private async Task<bool> CheckElasticsearchAsync()
    {
        try
        {
            var esUrl = _configuration.GetConnectionString("Elasticsearch") ?? "http://localhost:9200";
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            var response = await client.GetAsync($"{esUrl.TrimEnd('/')}/_cluster/health");
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking Elasticsearch health in stats service");
            return false;
        }
    }
}
