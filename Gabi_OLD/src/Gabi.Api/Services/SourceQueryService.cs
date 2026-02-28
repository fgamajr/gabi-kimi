// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Text.Json;
using Gabi.Contracts.Dashboard;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;

namespace Gabi.Api.Services;

/// <summary>
/// Provides source and link query operations (details, paginated links, safra breakdown).
/// </summary>
public interface ISourceQueryService
{
    Task<SourceDetailsResponse> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default);
    Task<LinkListResponse> GetLinksAsync(string sourceId, LinkListRequest request, CancellationToken ct = default);
    Task<DiscoveredLinkDetailDto?> GetLinkByIdAsync(string sourceId, long linkId, CancellationToken ct = default);
    Task<SafraResponse> GetSafraAsync(string? sourceId, CancellationToken ct = default);
}

public class SourceQueryService : ISourceQueryService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<SourceQueryService> _logger;

    public SourceQueryService(
        IServiceProvider serviceProvider,
        ILogger<SourceQueryService> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
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
        var useIntentGuardrails = IntentGuardrails.IsKnownIntent(request.QueryIntent);

        if (!useIntentGuardrails)
        {
            var paginated = await linkRepo.GetBySourcePaginatedAsync(
                sourceId, page, pageSize, request.Status, request.Sort, ct);

            var pageIds = paginated.Items.Select(l => l.Id).ToList();
            var docCounts = await linkRepo.GetDocumentCountBulkAsync(pageIds, ct);

            var linkDtos = paginated.Items
                .Select(link => MapToLinkDetailDto(link, docCounts.GetValueOrDefault(link.Id, 0)))
                .ToList();

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

        // Guardrail mode: apply intent filter before pagination to avoid mixing proposicao/norma.
        var guardrailWindow = await linkRepo.GetBySourcePaginatedAsync(
            sourceId, 1, 5000, request.Status, request.Sort, ct);

        var windowIds = guardrailWindow.Items.Select(l => l.Id).ToList();
        var windowDocCounts = await linkRepo.GetDocumentCountBulkAsync(windowIds, ct);

        var filtered = new List<DiscoveredLinkDetailDto>();
        foreach (var link in guardrailWindow.Items)
        {
            var dto = MapToLinkDetailDto(link, windowDocCounts.GetValueOrDefault(link.Id, 0));
            if (IntentGuardrails.Allows(request.QueryIntent, dto.Metadata))
                filtered.Add(dto);
        }

        var totalItems = filtered.Count;
        var totalPages = totalItems == 0 ? 0 : (int)Math.Ceiling(totalItems / (double)pageSize);
        var pageData = filtered
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToList();

        return new LinkListResponse
        {
            Data = pageData,
            Pagination = new PaginationInfo
            {
                Page = page,
                PageSize = pageSize,
                TotalItems = totalItems,
                TotalPages = totalPages
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

    // ═══════════════════════════════════════════════════════════════════════════
    // Private Helpers
    // ═══════════════════════════════════════════════════════════════════════════

    private DiscoveredLinkDetailDto MapToLinkDetailDto(
        DiscoveredLinkEntity link,
        int documentCount)
    {
        // Parse metadata
        Dictionary<string, object>? metadata = null;
        try
        {
            metadata = JsonSerializer.Deserialize<Dictionary<string, object>>(link.Metadata);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to parse metadata for link {LinkId}", link.Id);
        }

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
}
