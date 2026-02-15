// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Text.Json.Serialization;

namespace Gabi.Contracts.Dashboard;

/// <summary>
/// Dashboard source information matching the React frontend contract.
/// </summary>
public record DashboardSource
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = null!;

    [JsonPropertyName("description")]
    public string Description { get; init; } = null!;

    [JsonPropertyName("source_type")]
    public string SourceType { get; init; } = null!;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; init; }

    [JsonPropertyName("document_count")]
    public int DocumentCount { get; init; }
}

/// <summary>
/// Job status values matching the React frontend.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum SyncJobStatus
{
    Synced,
    Pending,
    Failed,
    InProgress
}

/// <summary>
/// Sync job information matching the React frontend contract.
/// </summary>
public record SyncJob
{
    [JsonPropertyName("source")]
    public string Source { get; init; } = null!;

    [JsonPropertyName("year")]
    [JsonConverter(typeof(YearJsonConverter))]
    public object Year { get; init; } = null!;

    [JsonPropertyName("status")]
    public SyncJobStatus Status { get; init; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; init; }
}

/// <summary>
/// Custom JSON converter to handle year as either number or string.
/// </summary>
public class YearJsonConverter : System.Text.Json.Serialization.JsonConverter<object>
{
    public override object Read(ref System.Text.Json.Utf8JsonReader reader, Type typeToConvert, System.Text.Json.JsonSerializerOptions options)
    {
        if (reader.TokenType == System.Text.Json.JsonTokenType.Number)
            return reader.GetInt32();
        if (reader.TokenType == System.Text.Json.JsonTokenType.String)
            return reader.GetString()!;
        throw new System.Text.Json.JsonException();
    }

    public override void Write(System.Text.Json.Utf8JsonWriter writer, object value, System.Text.Json.JsonSerializerOptions options)
    {
        if (value is int intValue)
            writer.WriteNumberValue(intValue);
        else if (value is string strValue)
            writer.WriteStringValue(strValue);
        else
            writer.WriteNullValue();
    }
}

/// <summary>
/// Pipeline stage names matching the React frontend.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum PipelineStageName
{
    Discovery,
    Ingest,
    Processing,
    Embedding,
    Indexing
}

/// <summary>
/// Pipeline stage status values matching the React frontend.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum PipelineStageStatus
{
    Active,
    Idle,
    Error
}

/// <summary>
/// Pipeline stage information matching the React frontend contract.
/// </summary>
public record PipelineStage
{
    [JsonPropertyName("name")]
    public PipelineStageName Name { get; init; }

    [JsonPropertyName("label")]
    public string Label { get; init; } = null!;

    [JsonPropertyName("description")]
    public string Description { get; init; } = null!;

    [JsonPropertyName("count")]
    public int Count { get; init; }

    [JsonPropertyName("total")]
    public int Total { get; init; }

    [JsonPropertyName("status")]
    public PipelineStageStatus Status { get; init; }

    [JsonPropertyName("lastActivity")]
    public string? LastActivity { get; init; }

    [JsonPropertyName("availability")]
    public string Availability { get; init; } = "available"; // "available" | "coming_soon"

    [JsonPropertyName("message")]
    public string? Message { get; init; } // Mensagem para estágios "coming_soon"
}

/// <summary>
/// Dashboard statistics response matching the React frontend contract.
/// </summary>
public record DashboardStatsResponse
{
    [JsonPropertyName("sources")]
    public IReadOnlyList<DashboardSource> Sources { get; init; } = Array.Empty<DashboardSource>();

    [JsonPropertyName("total_documents")]
    public int TotalDocuments { get; init; }

    [JsonPropertyName("elasticsearch_available")]
    public bool ElasticsearchAvailable { get; init; }

    [JsonPropertyName("sync_status")]
    public SyncStatusDto? SyncStatus { get; init; }

    [JsonPropertyName("throughput")]
    public ThroughputDto? Throughput { get; init; }

    [JsonPropertyName("rag_stats")]
    public RagStatsDto? RagStats { get; init; }
}

/// <summary>
/// Jobs response matching the React frontend contract.
/// </summary>
public record JobsResponse
{
    [JsonPropertyName("sync_jobs")]
    public IReadOnlyList<SyncJob> SyncJobs { get; init; } = Array.Empty<SyncJob>();

    [JsonPropertyName("elastic_indexes")]
    public Dictionary<string, int> ElasticIndexes { get; init; } = new();

    [JsonPropertyName("total_elastic_docs")]
    public int TotalElasticDocs { get; init; }
}

/// <summary>
/// System health status for the dashboard.
/// </summary>
public record SystemHealthResponse
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = "ok";

    [JsonPropertyName("timestamp")]
    public string Timestamp { get; init; } = DateTime.UtcNow.ToString("O");

    [JsonPropertyName("services")]
    public Dictionary<string, ServiceHealth> Services { get; init; } = new();
}

public record ServiceHealth
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = "unknown";

    [JsonPropertyName("response_time_ms")]
    public double? ResponseTimeMs { get; init; }

    [JsonPropertyName("message")]
    public string? Message { get; init; }
}

/// <summary>
/// Refresh source request.
/// </summary>
public record RefreshSourceRequest
{
    [JsonPropertyName("force")]
    public bool Force { get; init; } = false;

    [JsonPropertyName("year")]
    public int? Year { get; init; }
}

/// <summary>
/// Refresh source response.
/// </summary>
public record RefreshSourceResponse
{
    [JsonPropertyName("success")]
    public bool Success { get; init; }

    [JsonPropertyName("job_id")]
    public Guid? JobId { get; init; }

    [JsonPropertyName("message")]
    public string Message { get; init; } = null!;
}

/// <summary>
/// Resposta do seed: job enfileirado para o Worker processar (persistência com retry + registro em seed_runs).
/// </summary>
public record SeedResponse
{
    [JsonPropertyName("success")]
    public bool Success { get; init; }

    [JsonPropertyName("job_id")]
    public Guid? JobId { get; init; }

    [JsonPropertyName("message")]
    public string Message { get; init; } = null!;
}

/// <summary>
/// Última execução do seed (tabela seed_runs). Usado pela fase de discovery para saber se o catálogo está pronto.
/// </summary>
public record SeedRunDto
{
    [JsonPropertyName("id")]
    public Guid Id { get; init; }

    [JsonPropertyName("job_id")]
    public Guid JobId { get; init; }

    [JsonPropertyName("completed_at")]
    public DateTime CompletedAt { get; init; }

    [JsonPropertyName("sources_total")]
    public int SourcesTotal { get; init; }

    [JsonPropertyName("sources_seeded")]
    public int SourcesSeeded { get; init; }

    [JsonPropertyName("sources_failed")]
    public int SourcesFailed { get; init; }

    [JsonPropertyName("status")]
    public string Status { get; init; } = null!; // completed | partial | failed

    [JsonPropertyName("error_summary")]
    public string? ErrorSummary { get; init; }
}

/// <summary>
/// Última execução de discovery para uma fonte (tabela discovery_runs).
/// Usado pela fase fetch e pelo frontend para saber o resultado do discovery.
/// </summary>
public record DiscoveryRunDto
{
    [JsonPropertyName("id")]
    public Guid Id { get; init; }

    [JsonPropertyName("job_id")]
    public Guid JobId { get; init; }

    [JsonPropertyName("source_id")]
    public string SourceId { get; init; } = null!;

    [JsonPropertyName("completed_at")]
    public DateTime CompletedAt { get; init; }

    [JsonPropertyName("links_total")]
    public int LinksTotal { get; init; }

    [JsonPropertyName("status")]
    public string Status { get; init; } = null!; // completed | partial | failed

    [JsonPropertyName("error_summary")]
    public string? ErrorSummary { get; init; }
}

/// <summary>
/// Última execução de fetch para uma fonte (tabela fetch_runs).
/// </summary>
public record FetchRunDto
{
    [JsonPropertyName("id")]
    public Guid Id { get; init; }

    [JsonPropertyName("job_id")]
    public Guid JobId { get; init; }

    [JsonPropertyName("source_id")]
    public string SourceId { get; init; } = null!;

    [JsonPropertyName("completed_at")]
    public DateTime CompletedAt { get; init; }

    [JsonPropertyName("items_total")]
    public int ItemsTotal { get; init; }

    [JsonPropertyName("items_completed")]
    public int ItemsCompleted { get; init; }

    [JsonPropertyName("items_failed")]
    public int ItemsFailed { get; init; }

    [JsonPropertyName("status")]
    public string Status { get; init; } = null!;

    [JsonPropertyName("error_summary")]
    public string? ErrorSummary { get; init; }
}

/// <summary>
/// Fase do pipeline (para listagem no frontend: seed, discovery, fetch, ingest).
/// </summary>
public record PipelinePhaseDto
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = null!;

    [JsonPropertyName("name")]
    public string Name { get; init; } = null!;

    [JsonPropertyName("description")]
    public string Description { get; init; } = null!;

    [JsonPropertyName("availability")]
    public string Availability { get; init; } = "available"; // available | requires_previous | coming_soon

    [JsonPropertyName("trigger_endpoint")]
    public string TriggerEndpoint { get; init; } = null!;
}

// ============================================
// NOVOS CONTRATOS PARA DETALHAMENTO DE SOURCE
// ============================================

/// <summary>
/// Resposta paginada de links descobertos para uma source.
/// </summary>
public record LinkListResponse
{
    [JsonPropertyName("data")]
    public IReadOnlyList<DiscoveredLinkDetailDto> Data { get; init; } = Array.Empty<DiscoveredLinkDetailDto>();

    [JsonPropertyName("pagination")]
    public PaginationInfo Pagination { get; init; } = new();
}

/// <summary>
/// Informações de paginação para listagens.
/// </summary>
public record PaginationInfo
{
    [JsonPropertyName("page")]
    public int Page { get; init; }

    [JsonPropertyName("pageSize")]
    public int PageSize { get; init; }

    [JsonPropertyName("totalItems")]
    public int TotalItems { get; init; }

    [JsonPropertyName("totalPages")]
    public int TotalPages { get; init; }
}

/// <summary>
/// Detalhe completo de um link descoberto.
/// </summary>
public record DiscoveredLinkDetailDto
{
    [JsonPropertyName("id")]
    public long Id { get; init; }

    [JsonPropertyName("sourceId")]
    public string SourceId { get; init; } = null!;

    [JsonPropertyName("url")]
    public string Url { get; init; } = null!;

    [JsonPropertyName("status")]
    public string Status { get; init; } = null!;

    [JsonPropertyName("discoveredAt")]
    public string DiscoveredAt { get; init; } = null!;

    [JsonPropertyName("lastModified")]
    public string? LastModified { get; init; }

    [JsonPropertyName("etag")]
    public string? Etag { get; init; }

    [JsonPropertyName("contentLength")]
    public long? ContentLength { get; init; }

    [JsonPropertyName("contentHash")]
    public string? ContentHash { get; init; }

    [JsonPropertyName("documentCount")]
    public int DocumentCount { get; init; }

    [JsonPropertyName("processAttempts")]
    public int ProcessAttempts { get; init; }

    [JsonPropertyName("metadata")]
    public Dictionary<string, object>? Metadata { get; init; }

    [JsonPropertyName("pipeline")]
    public LinkPipelineStatusDto Pipeline { get; init; } = null!;
}

/// <summary>
/// Status do pipeline para um link específico.
/// </summary>
public record LinkPipelineStatusDto
{
    [JsonPropertyName("discovery")]
    public PipelineStageStatusDto Discovery { get; init; } = null!;

    [JsonPropertyName("ingest")]
    public PipelineStageStatusDto Ingest { get; init; } = null!;

    [JsonPropertyName("processing")]
    public PipelineStageStatusDto Processing { get; init; } = null!;

    [JsonPropertyName("embedding")]
    public PipelineStageStatusDto Embedding { get; init; } = null!;

    [JsonPropertyName("indexing")]
    public PipelineStageStatusDto Indexing { get; init; } = null!;
}

/// <summary>
/// Status de um estágio específico do pipeline.
/// </summary>
public record PipelineStageStatusDto
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = null!; // "completed", "planned", "active", "error"

    [JsonPropertyName("availability")]
    public string Availability { get; init; } = null!; // "available", "coming_soon"

    [JsonPropertyName("completedAt")]
    public string? CompletedAt { get; init; }

    [JsonPropertyName("message")]
    public string? Message { get; init; }
}

/// <summary>
/// Resposta com detalhes completos de uma source.
/// </summary>
public record SourceDetailsResponse
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = null!;

    [JsonPropertyName("name")]
    public string Name { get; init; } = null!;

    [JsonPropertyName("description")]
    public string? Description { get; init; }

    [JsonPropertyName("provider")]
    public string Provider { get; init; } = null!;

    [JsonPropertyName("discoveryStrategy")]
    public string DiscoveryStrategy { get; init; } = null!;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; init; }

    [JsonPropertyName("totalLinks")]
    public int TotalLinks { get; init; }

    [JsonPropertyName("lastRefresh")]
    public string? LastRefresh { get; init; }

    [JsonPropertyName("statistics")]
    public SourceStatisticsDto Statistics { get; init; } = null!;
}

/// <summary>
/// Estatísticas de uma source.
/// </summary>
public record SourceStatisticsDto
{
    [JsonPropertyName("linksByStatus")]
    public Dictionary<string, int> LinksByStatus { get; init; } = new();

    [JsonPropertyName("totalDocuments")]
    public int TotalDocuments { get; init; }

    [JsonPropertyName("lastDiscoveryAt")]
    public string? LastDiscoveryAt { get; init; }
}

/// <summary>
/// Parâmetros de requisição para listagem de links.
/// </summary>
public record LinkListRequest
{
    [JsonPropertyName("page")]
    public int Page { get; init; } = 1;

    [JsonPropertyName("pageSize")]
    public int PageSize { get; init; } = 20;

    [JsonPropertyName("status")]
    public string? Status { get; init; }

    [JsonPropertyName("sort")]
    public string? Sort { get; init; } = "discoveredAt_desc";
}

public record SyncStatusDto
{
    [JsonPropertyName("synced_count")]
    public int SyncedCount { get; init; }
    [JsonPropertyName("processing_count")]
    public int ProcessingCount { get; init; }
    [JsonPropertyName("total_count")]
    public int TotalCount { get; init; }
}

public record ThroughputDto
{
    [JsonPropertyName("docs_per_min")]
    public double DocsPerMin { get; init; }
    [JsonPropertyName("eta_minutes")]
    public double? EtaMinutes { get; init; }
}

public record RagStatsDto
{
    [JsonPropertyName("indexed_count")]
    public int IndexedCount { get; init; }
    [JsonPropertyName("indexed_percentage")]
    public double IndexedPercentage { get; init; }
    [JsonPropertyName("vector_chunks_count")]
    public int VectorChunksCount { get; init; }
    [JsonPropertyName("index_size_mb")]
    public double IndexSizeMb { get; init; }
}

public record SafraResponse
{
    [JsonPropertyName("years")]
    public IReadOnlyList<SafraYearStatsDto> Years { get; init; } = Array.Empty<SafraYearStatsDto>();
    [JsonPropertyName("throughput_docs_min")]
    public double ThroughputDocsMin { get; init; }
    [JsonPropertyName("rag_percentage")]
    public double RagPercentage { get; init; }
}

public record SafraYearStatsDto
{
    [JsonPropertyName("year")]
    public int Year { get; init; }
    
    [JsonPropertyName("sync_count")]
    public int SyncCount { get; init; }
    [JsonPropertyName("sync_total")]
    public int SyncTotal { get; init; }
    
    [JsonPropertyName("index_count")]
    public int IndexCount { get; init; }
    [JsonPropertyName("index_total")]
    public int IndexTotal { get; init; }
    
    [JsonPropertyName("rag_count")]
    public int RagCount { get; init; }
    [JsonPropertyName("rag_total")]
    public int RagTotal { get; init; }
    
    [JsonPropertyName("status")]
    public string Status { get; init; } = "pending";
}
