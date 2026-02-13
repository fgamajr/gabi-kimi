namespace Gabi.Contracts.Api;

/// <summary>
/// Contratos de rotas e versionamento da API GABI.
/// Padronizado para uso com Minimal API (ASP.NET MapGet/MapPost).
/// </summary>
public static class ApiRoutes
{
    /// <summary>Versão atual da API.</summary>
    public const string Version = "v1";
    
    /// <summary>Prefixo base da API.</summary>
    public const string Prefix = $"/api/{Version}";
    
    /// <summary>Template para rotas de sources.</summary>
    public const string Sources = $"{Prefix}/sources";
    
    /// <summary>Template para source específico.</summary>
    public const string SourceById = $"{Prefix}/sources/{{sourceId}}";
    
    /// <summary>Template para refresh de source.</summary>
    public const string SourceRefresh = $"{Prefix}/sources/{{sourceId}}/refresh";
    
    /// <summary>GET dashboard stats (sources, total documents, elasticsearch).</summary>
    public const string Stats = $"{Prefix}/stats";
    
    /// <summary>GET lista de jobs de sync + totais por índice.</summary>
    public const string Jobs = $"{Prefix}/jobs";
    
    /// <summary>GET estágios do pipeline (harvest, sync, ingest, index).</summary>
    public const string Pipeline = $"{Prefix}/pipeline";
    
    /// <summary>Template para health check.</summary>
    public const string Health = "/health";
    
    /// <summary>Template para readiness check.</summary>
    public const string HealthReady = "/health/ready";
}
