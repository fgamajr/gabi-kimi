using Gabi.Contracts.Dashboard;

namespace Gabi.Contracts.Api;

/// <summary>
/// Interface do catálogo de fontes de dados.
/// Implementada pelo Gabi.Api para servir dados ao frontend.
/// </summary>
public interface ISourceCatalog
{
    /// <summary>
    /// Lista todas as fontes disponíveis.
    /// </summary>
    Task<IReadOnlyList<SourceSummaryDto>> ListSourcesAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Obtém detalhes de uma fonte específica.
    /// </summary>
    Task<SourceDetailDto?> GetSourceAsync(string sourceId, CancellationToken ct = default);
    
    /// <summary>
    /// Executa refresh (re-discovery) de uma fonte.
    /// </summary>
    Task<RefreshResult> RefreshSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Lista os jobs de sincronização recentes e estatísticas de índices.
    /// </summary>
    Task<JobsResponseDto> ListSyncJobsAsync(CancellationToken ct = default);

    /// <summary>
    /// Obtém estatísticas globais do sistema.
    /// </summary>
    Task<SystemStatsDto> GetSystemStatsAsync(CancellationToken ct = default);

    /// <summary>
    /// Obtém o status de todas as fases do pipeline.
    /// </summary>
    Task<IReadOnlyList<PipelineStageDto>> GetPipelineStagesAsync(CancellationToken ct = default);

    /// <summary>
    /// Obtém o status do job mais recente de uma fonte (para polling no frontend).
    /// </summary>
    Task<JobStatusDto?> GetJobStatusForSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Obtém detalhes completos de uma fonte (granularidade para página de detalhes).
    /// </summary>
    Task<SourceDetailsResponse?> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Obtém links descobertos de uma fonte com paginação e filtro.
    /// </summary>
    Task<PagedResult<DiscoveredLinkDto>> GetLinksAsync(string sourceId, int page, int pageSize, string? status, string? sort, CancellationToken ct = default);
}
