namespace Gabi.Contracts.Api;

// ═════════════════════════════════════════════════════════════════════════════
// Response Envelopes
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Envelope padronizado para respostas de sucesso.
/// </summary>
public record ApiEnvelope<T>(T Data, string Version = ApiRoutes.Version);

/// <summary>
/// Envelope para respostas de erro.
/// </summary>
public record ApiError(string Code, string Message, string? Detail = null);

/// <summary>
/// Resultado paginado.
/// </summary>
public record PagedResult<T>(
    IReadOnlyList<T> Items,
    int Page,
    int PageSize,
    long TotalCount,
    int TotalPages
);

// ═════════════════════════════════════════════════════════════════════════════
// Source DTOs
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Resumo de uma fonte de dados (para listagem).
/// </summary>
public record SourceSummaryDto(
    string Id, 
    string Name, 
    string Provider, 
    string Strategy, 
    bool Enabled,
    int? DocumentCount = null,
    string? SourceType = null
);

/// <summary>
/// Detalhes completos de uma fonte.
/// </summary>
public record SourceDetailDto(
    string Id, 
    string Name, 
    string? Description, 
    string Provider, 
    string Strategy, 
    bool Enabled,
    IReadOnlyList<DiscoveredLinkDto> Links, 
    SourceMetadataDto Metadata
)
{
    /// <summary>
    /// Configuração de discovery (opcional, carregada dinamicamente).
    /// </summary>
    public Gabi.Contracts.Discovery.DiscoveryConfig? DiscoveryConfig { get; init; }
};

/// <summary>
/// Metadados de uma fonte.
/// </summary>
public record SourceMetadataDto(
    string? Domain, 
    string? Jurisdiction, 
    string? Category, 
    DateTime? LastRefreshed, 
    int? TotalLinks,
    /// <summary>Quando preenchido, indica que o discovery para este tipo de fonte ainda não está implementado (ex.: web_crawl, api_pagination).</summary>
    string? DiscoveryNotice = null
);

/// <summary>
/// Link descoberto.
/// </summary>
public record DiscoveredLinkDto(
    string Url, 
    DateTime DiscoveredAt, 
    string? Etag,
    string Status = "pending", // pending, processed, error
    long DocumentCount = 0,
    PipelineStatusDto? PipelineStatus = null
);

public record PipelineStatusDto(
    StageStatusDto Discovery,
    StageStatusDto Ingest,
    StageStatusDto Indexing
);

public record StageStatusDto(
    string Status, // active, planned, completed, error
    string? Message = null,
    DateTime? LastActivity = null
);

// ═════════════════════════════════════════════════════════════════════════════
// Dashboard DTOs
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Estatísticas globais do sistema.
/// </summary>
public record SystemStatsDto(
    IReadOnlyList<SourceSummaryDto> Sources,
    long TotalDocuments,
    bool ElasticsearchAvailable,
    DateTime LastUpdate
);

/// <summary>
/// Resposta consolidada para a visualização de jobs do dashboard.
/// </summary>
public record JobsResponseDto(
    IReadOnlyList<SyncJobDto> SyncJobs,
    long TotalElasticDocs,
    IReadOnlyDictionary<string, long> ElasticIndexes
);

/// <summary>
/// Status de um job de sincronização.
/// </summary>
public record SyncJobDto(
    string SourceId,
    string Year,
    string Status, // synced, pending, failed, in_progress
    DateTime? UpdatedAt
);

/// <summary>
/// Status de uma fase do pipeline.
/// </summary>
public record PipelineStageDto(
    string Name, // harvest, sync, ingest, index
    string Label,
    string Description,
    long Count,
    long Total,
    string Status, // active, idle, error
    DateTime? LastActivity
);

// ═════════════════════════════════════════════════════════════════════════════
// Refresh DTOs
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Request para refresh de uma fonte.
/// </summary>
public record RefreshRequest(string SourceId);

/// <summary>
/// Resultado de um refresh.
/// </summary>
public record RefreshResult(
    string SourceId, 
    int LinksDiscovered, 
    TimeSpan Duration
);

/// <summary>
/// Status de um job para exibição na API (polling por fonte).
/// </summary>
public record JobStatusDto(
    string JobId,
    string SourceId,
    string Status,
    int ProgressPercent,
    string? ProgressMessage,
    int LinksDiscovered,
    DateTime? StartedAt,
    DateTime? CompletedAt,
    string? ErrorMessage
);

// SourceDetailsResponse, SourceStatisticsDto and LinkIngestStatsDto are defined
// in Gabi.Contracts.Dashboard.DashboardModels.cs to align with the React frontend contract.
