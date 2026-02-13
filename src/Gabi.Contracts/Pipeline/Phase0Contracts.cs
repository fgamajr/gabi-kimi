using Gabi.Contracts.Discovery;

namespace Gabi.Contracts.Pipeline;

/// <summary>
/// Representa um link descoberto durante o Phase 0 com metadados completos.
/// </summary>
public record DiscoveredLink
{
    /// <summary>ID único do link (0 se novo).</summary>
    public long Id { get; init; }
    
    /// <summary>ID da fonte de origem.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>URL completa do recurso.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>Hash SHA256 da URL.</summary>
    public string UrlHash { get; init; } = string.Empty;
    
    /// <summary>ETag do recurso (para change detection).</summary>
    public string? Etag { get; init; }
    
    /// <summary>Data da última modificação do recurso.</summary>
    public DateTime? LastModified { get; init; }
    
    /// <summary>Tamanho do conteúdo em bytes (se disponível).</summary>
    public long? ContentLength { get; init; }
    
    /// <summary>Hash do conteúdo (se já processado anteriormente).</summary>
    public string? ContentHash { get; init; }
    
    /// <summary>Status do link no pipeline.</summary>
    public LinkDiscoveryStatus Status { get; init; } = LinkDiscoveryStatus.New;
    
    /// <summary>Metadados adicionais.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = new Dictionary<string, object>();
    
    /// <summary>Data da primeira descoberta.</summary>
    public DateTime FirstSeenAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>Data da última descoberta.</summary>
    public DateTime DiscoveredAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>Número estimado de documentos (para arquivos CSV, etc).</summary>
    public int? EstimatedDocumentCount { get; init; }
}

/// <summary>
/// Status de um link descoberto no Phase 0.
/// </summary>
public enum LinkDiscoveryStatus
{
    /// <summary>Link novo, ainda não existe no banco.</summary>
    New,
    
    /// <summary>Link existe mas metadados mudaram (ETag, Last-Modified, etc).</summary>
    Changed,
    
    /// <summary>Link existe e não mudou (pode ser ignorado).</summary>
    Unchanged,
    
    /// <summary>Link marcado para processamento.</summary>
    MarkedForProcessing
}

/// <summary>
/// Resultado completo da execução do Phase 0 (Discovery + Metadata + Comparison).
/// </summary>
public record Phase0Result
{
    /// <summary>ID da fonte processada.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Indica se a execução foi bem-sucedida.</summary>
    public bool Success { get; init; }
    
    /// <summary>Mensagem de erro (se Success=false).</summary>
    public string? ErrorMessage { get; init; }
    
    /// <summary>Total de links descobertos.</summary>
    public int DiscoveredLinksCount { get; init; }
    
    /// <summary>Total de links com metadados obtidos.</summary>
    public int MetadataFetchedCount { get; init; }
    
    /// <summary>Tamanho total estimado em bytes.</summary>
    public long TotalEstimatedSizeBytes { get; init; }
    
    /// <summary>Número total estimado de documentos.</summary>
    public int? TotalEstimatedDocuments { get; init; }
    
    /// <summary>Número de links novos.</summary>
    public int NewLinksCount { get; init; }
    
    /// <summary>Número de links atualizados.</summary>
    public int UpdatedLinksCount { get; init; }
    
    /// <summary>Número de links ignorados (sem mudanças).</summary>
    public int SkippedLinksCount { get; init; }
    
    /// <summary>Data/hora de início da execução.</summary>
    public DateTime StartedAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>Data/hora de término da execução.</summary>
    public DateTime CompletedAt { get; init; }
    
    /// <summary>Duração total da execução.</summary>
    public TimeSpan Duration => CompletedAt - StartedAt;
    
    /// <summary>Links prontos para o Phase 1 (Fetch).</summary>
    public IReadOnlyList<DiscoveredLink> LinksToProcess { get; init; } = Array.Empty<DiscoveredLink>();
}

/// <summary>
/// Opções para execução do Phase 0.
/// </summary>
public record Phase0Options
{
    /// <summary>
    /// Pula links existentes sem mudanças (evita re-processamento desnecessário).
    /// </summary>
    public bool SkipExisting { get; init; } = true;
    
    /// <summary>
    /// Número máximo de links a processar (null = ilimitado).
    /// </summary>
    public int? MaxLinks { get; init; }
    
    /// <summary>
    /// Busca metadados em paralelo.
    /// </summary>
    public bool ParallelMetadataFetch { get; init; } = true;
    
    /// <summary>
    /// Número máximo de requisições paralelas.
    /// </summary>
    public int MaxParallelism { get; init; } = 5;
    
    /// <summary>
    /// Timeout para requisições HEAD.
    /// </summary>
    public TimeSpan MetadataFetchTimeout { get; init; } = TimeSpan.FromSeconds(30);
}

/// <summary>
/// Interface do orquestrador do Phase 0.
/// </summary>
public interface IPhase0Orchestrator
{
    /// <summary>
    /// Executa o pipeline completo do Phase 0 para uma fonte.
    /// </summary>
    /// <param name="sourceId">ID da fonte a processar.</param>
    /// <param name="options">Opções de execução.</param>
    /// <param name="ct">Token de cancelamento.</param>
    /// <returns>Resultado da execução do Phase 0.</returns>
    Task<Phase0Result> RunAsync(string sourceId, Phase0Options options, CancellationToken ct = default);
}

/// <summary>
/// Interface para serviço de fetch de metadados (HEAD requests).
/// </summary>
public interface IMetadataFetcher
{
    /// <summary>
    /// Busca metadados de uma URL via HEAD request.
    /// </summary>
    Task<MetadataFetchResult> FetchAsync(string url, CancellationToken ct = default);
}

/// <summary>
/// Resultado do fetch de metadados.
/// </summary>
public record MetadataFetchResult
{
    /// <summary>Indica se o fetch foi bem-sucedido.</summary>
    public bool Success { get; init; }
    
    /// <summary>ETag do recurso.</summary>
    public string? Etag { get; init; }
    
    /// <summary>Last-Modified do recurso.</summary>
    public DateTime? LastModified { get; init; }
    
    /// <summary>Content-Length em bytes.</summary>
    public long? ContentLength { get; init; }
    
    /// <summary>Content-Type do recurso.</summary>
    public string? ContentType { get; init; }
    
    /// <summary>Mensagem de erro (se Success=false).</summary>
    public string? ErrorMessage { get; init; }
}

/// <summary>
/// Interface para comparação de links (change detection).
/// </summary>
public interface ILinkComparator
{
    /// <summary>
    /// Compara um link descoberto com a versão existente no banco.
    /// </summary>
    /// <param name="discovered">Link descoberto.</param>
    /// <param name="existing">Link existente no banco (null se novo).</param>
    /// <param name="fetchedMetadata">Metadados obtidos via HEAD.</param>
    /// <returns>Veredito da comparação.</returns>
    LinkComparisonResult Compare(
        DiscoveredSource discovered, 
        DiscoveredLink? existing, 
        MetadataFetchResult? fetchedMetadata);
}

/// <summary>
/// Resultado da comparação de um link.
/// </summary>
public record LinkComparisonResult
{
    /// <summary>Status após comparação.</summary>
    public LinkDiscoveryStatus Status { get; init; }
    
    /// <summary>Razão da decisão.</summary>
    public string Reason { get; init; } = string.Empty;
    
    /// <summary>Metadados atualizados do link.</summary>
    public DiscoveredLink UpdatedLink { get; init; } = null!;
}
