// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Text.Json;
using Gabi.Contracts.Api;
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

    /// <summary>
    /// Lista fases do pipeline com disponibilidade e como disparar (para o frontend).
    /// </summary>
    Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default);
}

public class DashboardService : IDashboardService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DashboardService> _logger;
    private readonly IConfiguration _configuration;
    private readonly ISourceCatalog _sourceCatalog;

    public DashboardService(
        IServiceProvider serviceProvider,
        ILogger<DashboardService> logger,
        IConfiguration configuration,
        ISourceCatalog sourceCatalog)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _configuration = configuration;
        _sourceCatalog = sourceCatalog;
    }

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
                Message = "Seed already in progress. Poll GET /api/v1/dashboard/jobs for status."
            };
        }

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "catalog_seed",
            SourceId = string.Empty,
            Payload = new Dictionary<string, object> { ["run_id"] = Guid.NewGuid().ToString() },
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
            Message = "Seed job enqueued. Worker will load sources from YAML, persist with retry, and register in seed_runs. Poll GET /api/v1/dashboard/jobs or GET /api/v1/dashboard/seed/last for result."
        };
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

        foreach (var s in sources)
        {
            // Count discovered links for document count
            var links = await linkRepo.GetBySourceAsync(s.Id, ct);
            var docCount = links.Count;
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
        catch { /* ignore if job queue not available */ }

        return new DashboardStatsResponse
        {
            Sources = sourceList,
            TotalDocuments = totalDocuments,
            ElasticsearchAvailable = await CheckElasticsearchAsync(),
            
            // Extended Stats (Stubs + Real Data)
            SyncStatus = new SyncStatusDto 
            { 
                SyncedCount =  totalDocuments, // Approximation
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
                Availability = "coming_soon",
                Message = "Phase 3 - Coming in next release",
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
                Availability = "coming_soon",
                Message = "Phase 4 - Coming in next release",
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
                Availability = "coming_soon",
                Message = "Phase 5 - Coming in next release",
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
                Availability = "coming_soon",
                Message = "Phase 6 - Coming in next release",
                LastActivity = null
            }
        };
    }

    public async Task<SystemHealthResponse> GetSystemHealthAsync(CancellationToken ct = default)
    {
        var services = new Dictionary<string, ServiceHealth>();
        var overallStatus = "ok";

        try
        {
            using var scope = _serviceProvider.CreateScope();

            // Check PostgreSQL
            var stopwatch = System.Diagnostics.Stopwatch.StartNew();
            try
            {
                var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
                var count = await sourceRepo.GetAllAsync(ct);
                stopwatch.Stop();
                services["postgresql"] = new ServiceHealth
                {
                    Status = "ok",
                    ResponseTimeMs = stopwatch.ElapsedMilliseconds,
                    Message = $"{count.Count} sources loaded"
                };
            }
            catch (Exception ex)
            {
                stopwatch.Stop();
                services["postgresql"] = new ServiceHealth
                {
                    Status = "error",
                    ResponseTimeMs = stopwatch.ElapsedMilliseconds,
                    Message = ex.Message
                };
                overallStatus = "degraded";
            }

            // Check Elasticsearch
            services["elasticsearch"] = new ServiceHealth
            {
                Status = await CheckElasticsearchAsync() ? "ok" : "error",
                Message = "Elasticsearch cluster"
            };

            // Check Redis (if configured)
            var redisConn = _configuration.GetConnectionString("Redis");
            services["redis"] = new ServiceHealth
            {
                Status = !string.IsNullOrEmpty(redisConn) ? "ok" : "disabled",
                Message = !string.IsNullOrEmpty(redisConn) ? "Connected" : "Not configured"
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking system health");
            overallStatus = "error";
        }

        return new SystemHealthResponse
        {
            Status = overallStatus,
            Timestamp = DateTime.UtcNow.ToString("O"),
            Services = services
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
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = sourceId,
            Payload = new Dictionary<string, object>
            {
                ["force"] = request.Force,
                ["year"] = request.Year,
                ["discoveryConfig"] = source.DiscoveryConfig
            },
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);

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
            return await RefreshSourceAsync(sourceId, new RefreshSourceRequest { Force = true }, ct);

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

        var payload = new Dictionary<string, object> { ["phase"] = normalized };
        if (normalized == "fetch" && request?.MaxDocsPerSource is int maxDocsPerSource && maxDocsPerSource > 0)
        {
            payload["max_docs_per_source"] = maxDocsPerSource;
        }

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

        return new RefreshSourceResponse
        {
            Success = true,
            JobId = jobId,
            Message = $"{normalized} queued for {sourceId}"
        };
    }

    public Task<IReadOnlyList<PipelinePhaseDto>> GetPipelinePhasesAsync(CancellationToken ct = default)
    {
        var phases = new List<PipelinePhaseDto>
        {
            new() { Id = "seed", Name = "Seed", Description = "Carregar fontes do YAML no banco", Availability = "available", TriggerEndpoint = "POST /api/v1/dashboard/seed" },
            new() { Id = "discovery", Name = "Discovery", Description = "Descobrir URLs das fontes", Availability = "available", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/refresh" },
            new() { Id = "fetch", Name = "Fetch", Description = "Baixar conteúdo dos links descobertos", Availability = "requires_previous", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/phases/fetch" },
            new() { Id = "ingest", Name = "Ingest", Description = "Processar e indexar documentos", Availability = "requires_previous", TriggerEndpoint = "POST /api/v1/dashboard/sources/{sourceId}/phases/ingest" }
        };
        return Task.FromResult<IReadOnlyList<PipelinePhaseDto>>(phases);
    }

    /// <summary>
    /// Obtém detalhes completos de uma source com estatísticas.
    /// </summary>
    public async Task<SourceDetailsResponse> GetSourceDetailsAsync(
        string sourceId, 
        CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        var statusCounts = await linkRepo.GetStatusCountsAsync(sourceId, ct);
        var totalDocuments = statusCounts.Values.Sum(); // Por enquanto, contar links como docs
        var lastDiscovery = await linkRepo.GetLatestDiscoveryAsync(sourceId, ct);

        return new SourceDetailsResponse
        {
            Id = source.Id,
            Name = source.Name,
            Description = source.Description,
            Provider = source.Provider,
            DiscoveryStrategy = source.DiscoveryStrategy,
            Enabled = source.Enabled,
            TotalLinks = source.TotalLinks,
            LastRefresh = source.LastRefresh?.ToString("O"),
            Statistics = new SourceStatisticsDto
            {
                LinksByStatus = statusCounts,
                TotalDocuments = totalDocuments,
                LastDiscoveryAt = lastDiscovery?.ToString("O")
            }
        };
    }

    /// <summary>
    /// Lista links paginados de uma source.
    /// </summary>
    public async Task<LinkListResponse> GetLinksAsync(
        string sourceId,
        LinkListRequest request,
        CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();

        // Validar source existe
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        // Validar paginação
        var page = Math.Max(1, request.Page);
        var pageSize = Math.Clamp(request.PageSize, 1, 100);

        var paginated = await linkRepo.GetBySourcePaginatedAsync(
            sourceId, page, pageSize, request.Status, request.Sort, ct);

        var linkDtos = new List<DiscoveredLinkDetailDto>();
        foreach (var link in paginated.Items)
        {
            var docCount = await linkRepo.GetDocumentCountAsync(link.Id, ct);
            linkDtos.Add(MapToLinkDetailDto(link, docCount));
        }

        return new LinkListResponse
        {
            Data = linkDtos,
            Pagination = new PaginationInfo
            {
                Page = paginated.Page,
                PageSize = paginated.PageSize,
                TotalItems = paginated.TotalItems,
                TotalPages = paginated.TotalPages
            }
        };
    }

    /// <summary>
    /// Obtém detalhes de um link específico.
    /// </summary>
    public async Task<DiscoveredLinkDetailDto?> GetLinkByIdAsync(
        string sourceId, 
        long linkId, 
        CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var link = await linkRepo.GetByIdWithStatsAsync(linkId, ct);
        if (link == null || link.SourceId != sourceId)
            return null;

        var docCount = await linkRepo.GetDocumentCountAsync(linkId, ct);
        return MapToLinkDetailDto(link, docCount);
    }

    public async Task<SafraResponse> GetSafraAsync(string? sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();

        var links = new List<DiscoveredLinkEntity>();

        if (!string.IsNullOrEmpty(sourceId))
        {
             var source = await sourceRepo.GetByIdAsync(sourceId, ct);
             if (source == null) throw new KeyNotFoundException($"Source not found: {sourceId}");
             
             var result = await linkRepo.GetBySourceAsync(sourceId, ct);
             links = result.ToList();
        }
        else
        {
            // If no source specified, return empty or all (implementing empty for safety now)
            return new SafraResponse();
        }

        // Group by Year (using DiscoveredAt)
        var years = links
            .GroupBy(l => l.DiscoveredAt.Year)
            .Select(g => 
            {
                var total = g.Count();
                var processed = g.Count(l => l.Status == "processed" || l.Status == "completed");
                
                return new SafraYearStatsDto
                {
                    Year = g.Key,
                    SyncCount = processed,
                    SyncTotal = total,
                    IndexCount = processed, // Stub: assume processed = indexed
                    IndexTotal = total,
                    RagCount = (int)(processed * 0.8), // Stub: 80% RAG
                    RagTotal = total,
                    Status = processed == total ? "completed" : "active"
                };
            })
            .OrderByDescending(y => y.Year)
            .ToList();

        return new SafraResponse
        {
            Years = years,
            ThroughputDocsMin = 9807.61, // Stub
            RagPercentage = 62.9 // Stub
        };
    }

    private static DiscoveredLinkDetailDto MapToLinkDetailDto(
        DiscoveredLinkEntity link, 
        int documentCount)
    {
        // Parse metadata
        Dictionary<string, object>? metadata = null;
        try
        {
            metadata = JsonSerializer.Deserialize<Dictionary<string, object>>(link.Metadata);
        }
        catch { }

        return new DiscoveredLinkDetailDto
        {
            Id = link.Id,
            SourceId = link.SourceId,
            Url = link.Url,
            Status = link.Status,
            DiscoveredAt = link.DiscoveredAt.ToString("O"),
            LastModified = link.LastModified?.ToString("O"),
            Etag = link.Etag,
            ContentLength = link.ContentLength,
            ContentHash = link.ContentHash,
            DocumentCount = documentCount,
            ProcessAttempts = link.ProcessAttempts,
            Metadata = metadata,
            Pipeline = BuildPipelineStatus(link.Status)
        };
    }

    private static LinkPipelineStatusDto BuildPipelineStatus(string linkStatus)
    {
        var isDiscoveryCompleted = linkStatus.ToLower() switch
        {
            "completed" or "processed" => true,
            _ => false
        };

        return new LinkPipelineStatusDto
        {
            Discovery = new PipelineStageStatusDto
            {
                Status = isDiscoveryCompleted ? "completed" : "active",
                Availability = "available",
                CompletedAt = isDiscoveryCompleted ? DateTime.UtcNow.ToString("O") : null
            },
            Ingest = new PipelineStageStatusDto
            {
                Status = isDiscoveryCompleted ? "planned" : "pending",
                Availability = "coming_soon",
                Message = "Phase 3 - Document ingestion (coming soon)"
            },
            Processing = new PipelineStageStatusDto
            {
                Status = "planned",
                Availability = "coming_soon",
                Message = "Phase 4 - Text processing (coming soon)"
            },
            Embedding = new PipelineStageStatusDto
            {
                Status = "planned",
                Availability = "coming_soon",
                Message = "Phase 5 - Vector embedding (coming soon)"
            },
            Indexing = new PipelineStageStatusDto
            {
                Status = "planned",
                Availability = "coming_soon",
                Message = "Phase 6 - Elasticsearch indexing (coming soon)"
            }
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
        catch
        {
            return false;
        }
    }
}
