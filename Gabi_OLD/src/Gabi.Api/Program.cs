using Elastic.Clients.Elasticsearch;
using Gabi.Api;
using Gabi.Api.Models;
using Gabi.Api.Configuration;
using Gabi.Api.Endpoints;
using Gabi.Api.Middleware;
using Gabi.Api.Security;
using Gabi.Api.Services;
using Gabi.Contracts.Api;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Graph;
using Gabi.Contracts.Jobs;
using Gabi.Ingest;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Serilog;
using Serilog.Formatting.Compact;
using Microsoft.EntityFrameworkCore;
using Hangfire;
using Hangfire.Dashboard;

var builder = WebApplication.CreateBuilder(args);

// Serilog: em Produção, JSON no console (Fly logs); em Dev, formato legível via appsettings
builder.Host.UseSerilog((context, _, configuration) =>
{
    configuration.ReadFrom.Configuration(context.Configuration);
    if (context.HostingEnvironment.IsProduction())
        configuration.WriteTo.Console(new CompactJsonFormatter());
});

// Fail fast in non-Development if embeddings URL is not set (DEF-19 / GAP-10)
if (!builder.Environment.IsDevelopment() && !builder.Environment.IsEnvironment("Testing"))
{
    var embeddingsUrlCheck = builder.Configuration["GABI_EMBEDDINGS_URL"] ?? builder.Configuration["Gabi:EmbeddingsUrl"];
    if (string.IsNullOrWhiteSpace(embeddingsUrlCheck))
        throw new InvalidOperationException(
            "GABI_EMBEDDINGS_URL is required in non-development. Configure via environment variable GABI_EMBEDDINGS_URL.");
}

// Database
var connectionString = builder.Configuration.GetConnectionString("Default");
if (string.IsNullOrWhiteSpace(connectionString) && !builder.Environment.IsEnvironment("Testing"))
{
    throw new InvalidOperationException(
        "ConnectionStrings:Default is required. Configure via environment variable ConnectionStrings__Default.");
}
if (!string.IsNullOrWhiteSpace(connectionString))
{
    builder.Services.AddDbContext<GabiDbContext>(options =>
        options.UseNpgsql(connectionString));
}

// Security Configuration
builder.Services.AddJwtAuthentication(builder.Configuration, builder.Environment);
builder.Services.AddAuthorizationPolicies();
builder.Services.AddRateLimitingConfig(builder.Configuration);
builder.Services.AddCorsConfig(builder.Configuration, builder.Environment);

// Services
builder.Services.AddScoped<IJwtTokenService, JwtTokenService>();
builder.Services.AddSingleton<IUserCredentialStore, UserCredentialStore>();
builder.Services.AddSingleton<UrlAllowlistValidator>();
builder.Services.AddSingleton<LocalMediaPathValidator>();
builder.Services.AddHttpClient("SourceProxy", client =>
{
    client.Timeout = TimeSpan.FromSeconds(90);
});

// Hangfire (enqueue + dashboard; Worker processa com Hangfire Server)
builder.Services.AddHangfireServices(connectionString);

// Repositories
builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();
builder.Services.AddScoped<HangfireJobQueueRepository>();
builder.Services.AddScoped<IJobQueueRepository>(sp => sp.GetRequiredService<HangfireJobQueueRepository>());

// Stub for Hangfire job serialization (Worker executes the real implementation)
builder.Services.AddScoped<IGabiJobRunner, Gabi.Api.Jobs.StubGabiJobRunner>();

// Source Catalog Service (PostgreSQL version)
// Registered as Singleton and as IHostedService so InitializeAsync runs at startup.
// Failures (missing YAML, parse errors) surface immediately instead of being swallowed.
builder.Services.AddSingleton<PostgreSqlSourceCatalogService>(sp =>
{
    var logger = sp.GetRequiredService<ILogger<PostgreSqlSourceCatalogService>>();
    var config = sp.GetRequiredService<IConfiguration>();
    var env = sp.GetRequiredService<IHostEnvironment>();
    return new PostgreSqlSourceCatalogService(sp, logger, config, env);
});
builder.Services.AddSingleton<ISourceCatalog>(sp => sp.GetRequiredService<PostgreSqlSourceCatalogService>());
builder.Services.AddHostedService(sp => sp.GetRequiredService<PostgreSqlSourceCatalogService>());

// Dashboard sub-services (extracted from DashboardService)
builder.Services.AddScoped<ISystemHealthService, SystemHealthService>();
builder.Services.AddScoped<ISourceControlService, SourceControlService>();
builder.Services.AddScoped<IPipelineStatsService, PipelineStatsService>();
builder.Services.AddScoped<ISourceQueryService, SourceQueryService>();

// Dashboard Service
builder.Services.AddScoped<IDashboardService, DashboardService>();

// Repositories for fan-out stores (pgvector + KG)
builder.Services.AddScoped<IDocumentEmbeddingRepository, DocumentEmbeddingRepository>();
builder.Services.AddScoped<IDocumentRelationshipRepository, DocumentRelationshipRepository>();

// Elasticsearch + Embedder + SearchService (busca híbrida BM25 + Vector + Graph + RRF)
var elasticsearchUrl = builder.Configuration["Gabi:ElasticsearchUrl"] ?? builder.Configuration.GetConnectionString("Elasticsearch");
var embeddingsUrl = builder.Configuration["GABI_EMBEDDINGS_URL"] ?? builder.Configuration["Gabi:EmbeddingsUrl"];
var embeddingsProvider = builder.Configuration["Embeddings:Provider"] ?? "auto";

if (!string.IsNullOrWhiteSpace(elasticsearchUrl))
{
    builder.Services.AddSingleton(new ElasticsearchClient(new ElasticsearchClientSettings(new Uri(elasticsearchUrl))));

    // Embedder: ONNX (when model present) > TEI > Hash — so hybrid search works without TEI
    if (embeddingsProvider.Equals("onnx", StringComparison.OrdinalIgnoreCase)
        || (embeddingsProvider.Equals("auto", StringComparison.OrdinalIgnoreCase) && string.IsNullOrWhiteSpace(embeddingsUrl)))
    {
        var modelDir = builder.Configuration["Embeddings:OnnxModelDir"] ?? "models/paraphrase-multilingual-MiniLM-L12-v2";
        var modelPath = Path.Combine(modelDir, "model.onnx");
        var vocabPath = Path.Combine(modelDir, "vocab.txt");
        if (File.Exists(modelPath) && File.Exists(vocabPath))
        {
            builder.Services.AddSingleton<IEmbedder>(sp => new OnnxEmbedder(
                modelPath, vocabPath,
                sp.GetRequiredService<ILogger<OnnxEmbedder>>(),
                builder.Configuration.GetValue<int>("Embeddings:BatchSize", 32)));
        }
        else if (!string.IsNullOrWhiteSpace(embeddingsUrl))
        {
            RegisterTeiEmbedder(builder.Services, builder.Configuration, embeddingsUrl);
        }
        else
        {
            builder.Services.AddSingleton<IEmbedder, HashEmbedder>();
        }
    }
    else if (embeddingsProvider.Equals("tei", StringComparison.OrdinalIgnoreCase)
             || (embeddingsProvider.Equals("auto", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(embeddingsUrl)))
    {
        RegisterTeiEmbedder(builder.Services, builder.Configuration, embeddingsUrl!);
    }
    else
    {
        builder.Services.AddSingleton<IEmbedder, HashEmbedder>();
    }

    builder.Services.AddScoped<ISearchService>(sp => new SearchService(
        sp.GetRequiredService<ElasticsearchClient>(),
        sp.GetRequiredService<IEmbedder>(),
        sp.GetRequiredService<ILogger<SearchService>>(),
        embeddingRepo: sp.GetRequiredService<IDocumentEmbeddingRepository>(),
        relationshipRepo: sp.GetRequiredService<IDocumentRelationshipRepository>(),
        indexName: null));
}

static void RegisterTeiEmbedder(IServiceCollection services, IConfiguration configuration, string teiUrl)
{
    var baseUrl = teiUrl.TrimEnd('/') + "/";
    services.AddHttpClient("TeiEmbedder", client =>
    {
        client.BaseAddress = new Uri(baseUrl);
        client.Timeout = TimeSpan.FromSeconds(30);
    });
    services.AddSingleton<TeiEmbedder>(sp => new TeiEmbedder(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient("TeiEmbedder"),
        sp.GetRequiredService<ILogger<TeiEmbedder>>()));
    services.AddSingleton<IEmbedder>(sp => sp.GetRequiredService<TeiEmbedder>());
}

// DLQ Service
builder.Services.AddScoped<IDlqService, DlqService>();

// Health checks
var healthBuilder = builder.Services.AddHealthChecks()
    .AddCheck("self", () => HealthCheckResult.Healthy(), tags: new[] { "live" });

if (!string.IsNullOrWhiteSpace(connectionString))
    healthBuilder.AddNpgSql(connectionString, name: "postgres", tags: new[] { "ready" });

builder.Services.AddObservabilityServices(builder.Configuration);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new() { Title = "GABI API", Version = "v1" });
});

var app = builder.Build();

// Aplicar migrations na subida quando em container (Zero Kelvin / deploy sem dotnet ef no host)
var runMigrations = string.Equals(Environment.GetEnvironmentVariable("GABI_RUN_MIGRATIONS"), "true", StringComparison.OrdinalIgnoreCase);
if (runMigrations && !string.IsNullOrWhiteSpace(connectionString))
{
    using (var scope = app.Services.CreateScope())
    {
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        db.Database.Migrate();
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// Middleware Pipeline - ORDEM É CRÍTICA
// ═════════════════════════════════════════════════════════════════════════════

// 1. Exception Handler (primeiro para capturar tudo)
app.UseGlobalExceptionHandler();

// 2. HTTPS e HSTS (em produção)
if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
}
app.UseHttpsRedirection();

// 3. Security Headers
app.UseSecurityHeaders();

// 4. CORS (antes de auth para permitir preflight)
app.UseCors("GabiCorsPolicy");

// 5. Request Size Limit
app.Use(async (context, next) =>
{
    // Limitar tamanho do request body via config.
    // Como upload binário está desabilitado por padrão, manter limite conservador.
    var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
    if (feature != null)
    {
        var configuredMb = builder.Configuration.GetValue<long?>("Gabi:Api:MaxRequestBodySizeMb") ?? 4;
        feature.MaxRequestBodySize = configuredMb * 1024 * 1024;
    }
    await next();
});

// 6. Authentication
app.UseAuthentication();

// 7. Rate Limiting (após auth para permitir partição por usuário; login continua particionado por IP)
app.UseRateLimiter();

// 8. Authorization
app.UseAuthorization();

// Hangfire Dashboard (requer usuário autenticado)
if (!string.IsNullOrWhiteSpace(connectionString))
{
    app.UseHangfireDashboard("/hangfire", new DashboardOptions
    {
        Authorization = new[] { new HangfireDashboardAuthFilter() }
    });
}

// Swagger em desenvolvimento
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// ═════════════════════════════════════════════════════════════════════════════
// Health Checks (públicos - para monitoring)
// ═════════════════════════════════════════════════════════════════════════════

app.MapHealthChecks(ApiRoutes.Health, new HealthCheckOptions
{
    Predicate = r => r.Tags.Contains("live")
});
app.MapHealthChecks(ApiRoutes.HealthReady, new HealthCheckOptions
{
    Predicate = _ => true
});

// ═════════════════════════════════════════════════════════════════════════════
// Auth Endpoints (públicos)
// ═════════════════════════════════════════════════════════════════════════════

app.MapPost("/api/v1/auth/login", async (
    LoginRequest request,
    IJwtTokenService tokenService,
    IUserCredentialStore userCredentialStore,
    CancellationToken ct) =>
{
    if (!userCredentialStore.TryValidate(request.Username, request.Password, out var role))
    {
        return Results.Unauthorized();
    }

    var token = tokenService.GenerateToken(request.Username, role);
    return Results.Ok(new LoginResponse(true, token, null, role));
})
.RequireRateLimiting("auth");

app.MapMediaEndpoints();

// ═════════════════════════════════════════════════════════════════════════════
// Sources API (protegidos)
// ═════════════════════════════════════════════════════════════════════════════

// GET /api/v1/sources - List all sources
app.MapGet(ApiRoutes.Sources, [Authorize(Policy = "RequireViewer")] async (ISourceCatalog catalog, CancellationToken ct) =>
{
    var sources = await catalog.ListSourcesAsync(ct);
    return Results.Ok(new ApiEnvelope<IReadOnlyList<SourceSummaryDto>>(sources));
})
.RequireRateLimiting("read");

// GET /api/v1/sources/{sourceId} - Get source details
app.MapGet(ApiRoutes.SourceById, [Authorize(Policy = "RequireViewer")] async (string sourceId, ISourceCatalog catalog, CancellationToken ct) =>
{
    var source = await catalog.GetSourceAsync(sourceId, ct);
    return source != null
        ? Results.Ok(new ApiEnvelope<SourceDetailDto>(source))
        : Results.NotFound(new ApiError("SOURCE_NOT_FOUND", $"Source '{sourceId}' not found"));
})
.RequireRateLimiting("read");

// GET /api/v1/jobs/{sourceId}/status - Get job status for a source
app.MapGet("/api/v1/jobs/{sourceId}/status", [Authorize(Policy = "RequireViewer")] async (string sourceId, IJobQueueRepository jobQueue, CancellationToken ct) =>
{
    var status = await jobQueue.GetJobStatusDtoAsync(sourceId, ct);
    return Results.Ok(new ApiEnvelope<Gabi.Contracts.Api.JobStatusDto?>(
        status == null ? null : new Gabi.Contracts.Api.JobStatusDto(
            status.JobId,
            status.SourceId,
            status.Status,
            status.ProgressPercent,
            status.ProgressMessage,
            status.LinksDiscovered,
            status.StartedAt,
            status.CompletedAt,
            status.ErrorMessage
        )));
})
.RequireRateLimiting("read");

// GET /api/v1/search - Busca híbrida (ES: BM25 + kNN + RRF) ou fallback PostgreSQL (LIKE).
// CODEX-E: Quando ISearchService está configurado (ES + TEI), usa SearchService; senão usa busca textual no PG.
// Se Gabi:Search:RequireElasticsearch=true e ES não estiver configurado, retorna 503 (evita DoS por full table scan em produção).
app.MapGet("/api/v1/search", [Authorize(Policy = "RequireViewer")] async (
    HttpContext httpContext,
    string q,
    string? sourceId,
    int page,
    int pageSize,
    GabiDbContext db,
    CancellationToken ct) =>
{
    var queryText = (q ?? string.Empty).Trim();
    if (string.IsNullOrWhiteSpace(queryText))
        return Results.BadRequest(new ApiError("missing_query", "q is required"));

    var safePage = page > 0 ? page : 1;
    var safePageSize = Math.Clamp(pageSize > 0 ? pageSize : 20, 1, 100);

    var searchService = httpContext.RequestServices.GetService<ISearchService>();
    // Default to true in non-Development to prevent O(N) full table scan fallback in production (GEMINI-01)
    var env = httpContext.RequestServices.GetRequiredService<IHostEnvironment>();
    var requireEs = httpContext.RequestServices.GetRequiredService<IConfiguration>()
        .GetValue<bool>("Gabi:Search:RequireElasticsearch", !env.IsDevelopment());
    if (requireEs && searchService == null)
        return Results.Json(
            new ApiError("search_disabled", "Search requires Elasticsearch; not configured. Set Gabi:ElasticsearchUrl and GABI_EMBEDDINGS_URL (or Gabi:EmbeddingsUrl)."),
            statusCode: 503);

    if (searchService != null)
    {
        var result = await searchService.SearchAsync(queryText, sourceId, safePage, safePageSize, ct);
        if (result != null)
            return Results.Ok(result);
    }

    var query = db.Documents
        .AsNoTracking()
        .Where(d => d.Status == "completed" && d.RemovedFromSourceAt == null);

    if (!string.IsNullOrWhiteSpace(sourceId))
        query = query.Where(d => d.SourceId == sourceId);

    var tokens = queryText
        .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Select(t => t.Trim().ToLowerInvariant())
        .Where(t => t.Length >= 2)
        .Distinct()
        .ToArray();
    if (tokens.Length == 0)
        tokens = new[] { queryText.ToLowerInvariant() };

    foreach (var token in tokens)
    {
        var capturedToken = token;
        query = query.Where(d =>
            (d.Title ?? string.Empty).ToLower().Contains(capturedToken) ||
            (d.Content ?? string.Empty).ToLower().Contains(capturedToken));
    }

    var total = await query.CountAsync(ct);
    var rows = await query
        .OrderByDescending(d => d.UpdatedAt)
        .ThenByDescending(d => d.CreatedAt)
        .Skip((safePage - 1) * safePageSize)
        .Take(safePageSize)
        .Select(d => new
        {
            d.Id,
            d.SourceId,
            d.ExternalId,
            d.Title,
            d.Content,
            d.UpdatedAt,
            d.Metadata
        })
        .ToListAsync(ct);

    static string? ReadMetadataValue(string? metadataJson, params string[] keys)
    {
        if (string.IsNullOrWhiteSpace(metadataJson))
            return null;
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(metadataJson);
            if (doc.RootElement.ValueKind != System.Text.Json.JsonValueKind.Object)
                return null;
            foreach (var key in keys)
            {
                if (doc.RootElement.TryGetProperty(key, out var value))
                {
                    var text = value.ValueKind switch
                    {
                        System.Text.Json.JsonValueKind.String => value.GetString(),
                        System.Text.Json.JsonValueKind.Number => value.GetRawText(),
                        System.Text.Json.JsonValueKind.True => "true",
                        System.Text.Json.JsonValueKind.False => "false",
                        _ => null
                    };
                    if (!string.IsNullOrWhiteSpace(text))
                        return text;
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    static string? ReadMetadataUrl(string? metadataJson, params string[] keys)
        => ReadMetadataValue(metadataJson, keys);

    var hits = rows.Select(d => new SearchHitDto(
        Id: d.Id.ToString(),
        SourceId: d.SourceId,
        ExternalId: d.ExternalId,
        Title: d.Title,
        UpdatedAt: d.UpdatedAt,
        Snippet: string.IsNullOrWhiteSpace(d.Content) ? string.Empty : (d.Content!.Length <= 240 ? d.Content : d.Content[..240]),
        SourceViewUrl: ReadMetadataUrl(d.Metadata, "source_view_url", "view_url", "url"),
        SourceDownloadUrl: ReadMetadataUrl(d.Metadata, "source_download_url", "download_url", "url"),
        SourcePdfUrl: ReadMetadataUrl(d.Metadata, "source_pdf_url", "pdf_url", "source_download_url"),
        SourceAccessibleUrl: $"/api/v1/documents/{d.Id}/source-file",
        Section: ReadMetadataValue(d.Metadata, "secao", "section"),
        PublicationDate: ReadMetadataValue(d.Metadata, "data_publicacao", "publication_date"),
        PageStart: ReadMetadataValue(d.Metadata, "page_start", "pagina"),
        PageEnd: ReadMetadataValue(d.Metadata, "page_end", "pagina")
    ));

    return Results.Ok(new SearchResultDto(
        Query: queryText,
        Total: total,
        Page: safePage,
        PageSize: safePageSize,
        Hits: hits.ToList(),
        LatencyMs: 0
    ));
})
.RequireRateLimiting("read");

// GET /api/v1/documents/{id}/source-file - Streams official source file via backend proxy.
app.MapGet("/api/v1/documents/{id:guid}/source-file", async (
    Guid id,
    GabiDbContext db,
    IHttpClientFactory httpClientFactory,
    IConfiguration configuration,
    CancellationToken ct) =>
{
    var doc = await db.Documents.AsNoTracking()
        .Where(d => d.Id == id)
        .Select(d => new { d.Id, d.Metadata })
        .FirstOrDefaultAsync(ct);
    if (doc == null)
        return Results.NotFound(new ApiError("not_found", "Document not found."));

    static string? ReadFromJson(string json, params string[] keys)
    {
        if (string.IsNullOrWhiteSpace(json))
            return null;
        try
        {
            using var parsed = System.Text.Json.JsonDocument.Parse(json);
            if (parsed.RootElement.ValueKind != System.Text.Json.JsonValueKind.Object)
                return null;
            foreach (var key in keys)
            {
                if (!parsed.RootElement.TryGetProperty(key, out var value))
                    continue;
                var text = value.ValueKind == System.Text.Json.JsonValueKind.String
                    ? value.GetString()
                    : value.GetRawText();
                if (!string.IsNullOrWhiteSpace(text))
                    return text;
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    var targetUrl = ReadFromJson(doc.Metadata, "source_download_url", "source_pdf_url", "source_view_url");
    if (string.IsNullOrWhiteSpace(targetUrl) || !Uri.TryCreate(targetUrl, UriKind.Absolute, out var uri))
        return Results.BadRequest(new ApiError("invalid_source_url", "Document does not contain a valid source URL."));

    if (!string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase)
        && !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
    {
        return Results.BadRequest(new ApiError("invalid_scheme", "Only http/https source URLs are supported."));
    }

    var allowedHosts = configuration.GetSection("Gabi:SourceProxy:AllowedHosts").Get<string[]>()
        ?? ["inlabs.in.gov.br", "www.in.gov.br", "in.gov.br"];
    if (!allowedHosts.Any(h => uri.Host.Equals(h, StringComparison.OrdinalIgnoreCase)))
        return Results.BadRequest(new ApiError("host_not_allowed", "Source host is not allowed by proxy policy."));

    using var request = new HttpRequestMessage(HttpMethod.Get, uri);
    var cookie = Environment.GetEnvironmentVariable("GABI_INLABS_COOKIE");
    if (!string.IsNullOrWhiteSpace(cookie) && uri.Host.Contains("inlabs.in.gov.br", StringComparison.OrdinalIgnoreCase))
        request.Headers.TryAddWithoutValidation("Cookie", cookie);

    var client = httpClientFactory.CreateClient("SourceProxy");
    using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
    if (!response.IsSuccessStatusCode)
        return Results.StatusCode((int)response.StatusCode);

    var contentType = response.Content.Headers.ContentType?.ToString() ?? "application/octet-stream";
    var bytes = await response.Content.ReadAsByteArrayAsync(ct);
    return Results.File(bytes, contentType);
})
.RequireRateLimiting("read");

// POST /api/v1/dashboard/seed - Enfileira job de seed (Worker persiste YAML no banco com retry e registra em seed_runs)
app.MapPost("/api/v1/dashboard/seed", [Authorize(Policy = "RequireOperator")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var result = await dashboard.SeedSourcesAsync(ct);
    return Results.Ok(result);
})
.RequireRateLimiting("write");

// GET /api/v1/dashboard/seed/last - Última execução do seed (para discovery saber se o catálogo está pronto)
app.MapGet("/api/v1/dashboard/seed/last", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var last = await dashboard.GetLastSeedRunAsync(ct);
    return last != null ? Results.Ok(last) : Results.NotFound();
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/discovery/last - Última execução de discovery (opcional: ?sourceId= para filtrar por fonte)
app.MapGet("/api/v1/dashboard/discovery/last", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, string? sourceId, CancellationToken ct) =>
{
    var last = await dashboard.GetLastDiscoveryRunAsync(sourceId, ct);
    return last != null ? Results.Ok(last) : Results.NotFound();
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/sources/{sourceId}/discovery/last - Última execução de discovery para a fonte
app.MapGet("/api/v1/dashboard/sources/{sourceId}/discovery/last", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, string sourceId, CancellationToken ct) =>
{
    var last = await dashboard.GetLastDiscoveryRunAsync(sourceId, ct);
    return last != null ? Results.Ok(last) : Results.NotFound();
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/fetch/last - Última execução de fetch (opcional: ?sourceId= para filtrar por fonte)
app.MapGet("/api/v1/dashboard/fetch/last", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, string? sourceId, CancellationToken ct) =>
{
    var last = await dashboard.GetLastFetchRunAsync(sourceId, ct);
    return last != null ? Results.Ok(last) : Results.NotFound();
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/sources/{sourceId}/fetch/last - Última execução de fetch para a fonte
app.MapGet("/api/v1/dashboard/sources/{sourceId}/fetch/last", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, string sourceId, CancellationToken ct) =>
{
    var last = await dashboard.GetLastFetchRunAsync(sourceId, ct);
    return last != null ? Results.Ok(last) : Results.NotFound();
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/pipeline/phases - List pipeline phases (seed, discovery, fetch, ingest) for frontend
app.MapGet("/api/v1/dashboard/pipeline/phases", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var phases = await dashboard.GetPipelinePhasesAsync(ct);
    return Results.Ok(phases);
})
.RequireRateLimiting("read");

// POST /api/v1/dashboard/sources/{sourceId}/phases/{phase} - Start a pipeline phase (discovery | fetch | ingest)
app.MapGet("/api/v1/dashboard/sources/{sourceId}/state", [Authorize(Policy = "RequireViewer")] async (string sourceId, IDashboardService dashboard, CancellationToken ct) =>
{
    var state = await dashboard.GetSourcePipelineStateAsync(sourceId, ct);
    return state == null ? Results.NotFound() : Results.Ok(state);
});
app.MapPost("/api/v1/dashboard/sources/{sourceId}/pause", [Authorize(Policy = "RequireOperator")] async (string sourceId, IDashboardService dashboard, CancellationToken ct) =>
{
    var result = await dashboard.PauseSourceAsync(sourceId, pausedBy: null, ct);
    return Results.Ok(result);
});
app.MapPost("/api/v1/dashboard/sources/{sourceId}/resume", [Authorize(Policy = "RequireOperator")] async (string sourceId, IDashboardService dashboard, CancellationToken ct) =>
{
    var result = await dashboard.ResumeSourceAsync(sourceId, ct);
    return Results.Ok(result);
});
app.MapPost("/api/v1/dashboard/sources/{sourceId}/stop", [Authorize(Policy = "RequireOperator")] async (string sourceId, IDashboardService dashboard, CancellationToken ct) =>
{
    var result = await dashboard.StopSourceAsync(sourceId, ct);
    return Results.Ok(result);
});
app.MapPost("/api/v1/dashboard/sources/{sourceId}/phases/{phase}", [Authorize(Policy = "RequireOperator")] async (
    string sourceId,
    string phase,
    StartPhaseRequest? request,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(phase) || !new[] { "discovery", "fetch", "ingest" }.Contains(phase.ToLowerInvariant()))
        return Results.BadRequest(new ApiError("invalid_phase", "phase must be discovery, fetch, or ingest"));
    var result = await dashboard.StartPhaseAsync(sourceId, phase, request, ct);
    return result.Success ? Results.Ok(result) : Results.NotFound(result);
})
.RequireRateLimiting("write");

app.MapPost("/api/v1/dashboard/sources/{sourceId}/run-pipeline", [Authorize(Policy = "RequireOperator")] async (
    string sourceId,
    StartPhaseRequest? request,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    var result = await dashboard.RunPipelineAsync(sourceId, request, ct);
    return result.Success ? Results.Ok(result) : Results.NotFound(result);
})
.RequireRateLimiting("write");

// GET /api/v1/dashboard/sources/{sourceId}/metrics - Actionable metrics by source (DEF-16/17)
app.MapGet("/api/v1/dashboard/sources/{sourceId}/metrics", [Authorize(Policy = "RequireViewer")] async (
    string sourceId,
    GabiDbContext db,
    CancellationToken ct) =>
{
    var docStats = await db.Documents
        .AsNoTracking()
        .Where(d => d.SourceId == sourceId)
        .GroupBy(d => d.Status)
        .Select(g => new { Status = g.Key, Count = g.Count() })
        .ToListAsync(ct);

    var docsCompleted = docStats.FirstOrDefault(x => x.Status == "completed")?.Count ?? 0;
    var docsPending = docStats.FirstOrDefault(x => x.Status == "pending")?.Count ?? 0;
    var docsFailed = docStats.FirstOrDefault(x => x.Status == "failed")?.Count ?? 0;
    var docsTotal = docStats.Sum(x => x.Count);
    var docsSuccessRate = (docsCompleted + docsFailed) > 0
        ? Math.Round(docsCompleted / (double)(docsCompleted + docsFailed), 4)
        : 0.0;

    var jobStats = await db.JobRegistry
        .AsNoTracking()
        .Where(j => j.SourceId == sourceId)
        .GroupBy(j => j.Status)
        .Select(g => new { Status = g.Key, Count = g.Count() })
        .ToListAsync(ct);

    var jobsSucceeded = jobStats.FirstOrDefault(x => x.Status == "succeeded")?.Count ?? 0;
    var jobsFailed = jobStats.FirstOrDefault(x => x.Status == "failed")?.Count ?? 0;
    var jobsProcessing = jobStats.FirstOrDefault(x => x.Status == "processing")?.Count ?? 0;
    var jobsPending = jobStats.FirstOrDefault(x => x.Status == "pending")?.Count ?? 0;
    var jobsTotal = jobStats.Sum(x => x.Count);
    var jobsErrorRate = (jobsSucceeded + jobsFailed) > 0
        ? Math.Round(jobsFailed / (double)(jobsSucceeded + jobsFailed), 4)
        : 0.0;

    return Results.Ok(new
    {
        sourceId,
        docs = new
        {
            completed = docsCompleted,
            pending = docsPending,
            failed = docsFailed,
            total = docsTotal,
            success_rate = docsSuccessRate
        },
        jobs = new
        {
            succeeded = jobsSucceeded,
            failed = jobsFailed,
            processing = jobsProcessing,
            pending = jobsPending,
            total = jobsTotal,
            error_rate = jobsErrorRate
        }
    });
})
.RequireRateLimiting("read");

// POST /admin/sources/{sourceId}/reindex - Reindex: set active docs to pending and enqueue ingest (Admin only)
app.MapPost("/api/v1/admin/sources/{sourceId}/reindex", [Authorize(Policy = "RequireAdmin")] async (
    string sourceId,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(sourceId))
        return Results.BadRequest(new ApiError("missing_sourceId", "sourceId is required"));
    var result = await dashboard.ReindexSourceAsync(sourceId, ct);
    return result != null ? Results.Ok(result) : Results.NotFound(new ApiError("source_not_found", $"Source '{sourceId}' not found"));
})
.RequireRateLimiting("write");

// Novos endpoints de links (protegidos)
app.MapGet("/api/v1/sources/{sourceId}/links", [Authorize(Policy = "RequireViewer")] async (
    string sourceId,
    [AsParameters] LinkListRequest request,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    try
    {
        var result = await dashboard.GetLinksAsync(sourceId, request, ct);
        return Results.Ok(result);
    }
    catch (KeyNotFoundException)
    {
        return Results.NotFound(new ApiError("source_not_found", $"Source '{sourceId}' not found"));
    }
})
.RequireRateLimiting("read");

app.MapGet("/api/v1/sources/{sourceId}/links/{linkId:long}", [Authorize(Policy = "RequireViewer")] async (
    string sourceId,
    long linkId,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    var link = await dashboard.GetLinkByIdAsync(sourceId, linkId, ct);
    return link != null ? Results.Ok(link) : Results.NotFound();
})
.RequireRateLimiting("read");

// ═════════════════════════════════════════════════════════════════════════════
// Graph/Related Documents Endpoints
// ═════════════════════════════════════════════════════════════════════════════

// GET /api/v1/documents/{id} - Get a single document by ID (for MCP / clients)
app.MapGet("/api/v1/documents/{id:guid}", [Authorize(Policy = "RequireViewer")] async (
    Guid id,
    GabiDbContext db,
    CancellationToken ct) =>
{
    var doc = await db.Documents
        .AsNoTracking()
        .Where(d => d.Id == id)
        .Select(d => new { d.Id, d.SourceId, d.ExternalId, d.Title, d.Content, d.Status, d.Metadata, d.CreatedAt })
        .FirstOrDefaultAsync(ct);
    return doc is null ? Results.NotFound() : Results.Ok(new ApiEnvelope<object>(doc));
})
.RequireRateLimiting("read");

// GET /api/v1/documents/{id}/related - Traverse KG edges from a document
app.MapGet("/api/v1/documents/{id:guid}/related", [Authorize(Policy = "RequireViewer")] async (
    Guid id,
    IDocumentRelationshipRepository relationshipRepo,
    CancellationToken ct) =>
{
    var relations = await relationshipRepo.GetRelationshipsAsync(id, ct);
    return Results.Ok(new ApiEnvelope<IReadOnlyList<DocumentRelation>>(relations));
})
.RequireRateLimiting("read");

// GET /api/v1/graph/search?ref={pattern} - Search by legal reference pattern
app.MapGet("/api/v1/graph/search", [Authorize(Policy = "RequireViewer")] async (
    string @ref,
    int? topK,
    IDocumentRelationshipRepository relationshipRepo,
    CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(@ref))
        return Results.BadRequest(new ApiError("missing_ref", "ref query parameter is required"));
    var safeTopK = Math.Clamp(topK ?? 20, 1, 100);
    var results = await relationshipRepo.SearchByRefAsync(@ref, safeTopK, ct);
    return Results.Ok(new ApiEnvelope<IReadOnlyList<GraphSearchResult>>(results));
})
.RequireRateLimiting("read");

// ═════════════════════════════════════════════════════════════════════════════
// DLQ (Dead Letter Queue) Endpoints
// ═════════════════════════════════════════════════════════════════════════════

// GET /api/v1/dlq - List DLQ entries
app.MapGet("/api/v1/dlq", [Authorize(Policy = "RequireViewer")] async (
    int page,
    int pageSize,
    string? status,
    IDlqService dlqService,
    CancellationToken ct) =>
{
    var result = await dlqService.GetEntriesAsync(page > 0 ? page : 1, pageSize > 0 ? pageSize : 20, status, ct);
    return Results.Ok(result);
})
.RequireRateLimiting("read");

// GET /api/v1/dlq/stats - DLQ statistics
app.MapGet("/api/v1/dlq/stats", [Authorize(Policy = "RequireViewer")] async (
    IDlqService dlqService,
    CancellationToken ct) =>
{
    var stats = await dlqService.GetStatsAsync(ct);
    return Results.Ok(stats);
})
.RequireRateLimiting("read");

// GET /api/v1/dlq/{id} - Get single DLQ entry
app.MapGet("/api/v1/dlq/{id:guid}", [Authorize(Policy = "RequireViewer")] async (
    Guid id,
    IDlqService dlqService,
    CancellationToken ct) =>
{
    var entry = await dlqService.GetEntryAsync(id, ct);
    return entry != null ? Results.Ok(entry) : Results.NotFound();
})
.RequireRateLimiting("read");

// POST /api/v1/dlq/{id}/replay - Replay a DLQ entry
app.MapPost("/api/v1/dlq/{id:guid}/replay", [Authorize(Policy = "RequireOperator")] async (
    Guid id,
    string? notes,
    IDlqService dlqService,
    CancellationToken ct) =>
{
    var result = await dlqService.ReplayAsync(id, notes, ct);
    return result.Success
        ? Results.Ok(result)
        : Results.BadRequest(result);
})
.RequireRateLimiting("write");

// POST /api/v1/admin/sources/{sourceId}/repair-projection
// Enqueues a chunk_and_extract repair job for documents missing from ES.
// Authorization: RequireAdmin
app.MapPost("/api/v1/admin/sources/{sourceId}/repair-projection", [Authorize(Policy = "RequireAdmin")] async (
    string sourceId,
    RepairProjectionRequest? body,
    GabiDbContext db,
    IJobQueueRepository jobQueue,
    CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(sourceId))
        return Results.BadRequest(new ApiError("missing_sourceId", "sourceId is required"));

    var sourceExists = await db.SourceRegistries.AsNoTracking().AnyAsync(s => s.Id == sourceId, ct);
    if (!sourceExists)
        return Results.NotFound(new ApiError("source_not_found", $"Source '{sourceId}' not found"));

    // Optionally reset status to pending_projection for docs missing an ES ID
    if (body?.ResetStatus == true)
    {
        await db.Documents
            .Where(d => d.SourceId == sourceId && d.ElasticsearchId == null
                        && (d.Status == "active" || d.Status == "completed"))
            .ExecuteUpdateAsync(s => s.SetProperty(d => d.Status, "pending_projection"), ct);
    }

    // Find pending_projection documents
    var docIds = await db.Documents
        .Where(d => d.SourceId == sourceId && d.Status == "pending_projection")
        .Select(d => d.Id)
        .Take(1000)
        .ToListAsync(ct);

    if (docIds.Count == 0)
        return Results.Ok(new { queued = 0, jobId = (Guid?)null, message = "No pending_projection documents found" });

    var jobId = Guid.NewGuid();
    await jobQueue.EnqueueAsync(new IngestJob
    {
        Id = jobId,
        SourceId = sourceId,
        JobType = "chunk_and_extract",
        Payload = new Dictionary<string, object>
        {
            ["document_ids"] = docIds.Select(id => id.ToString()).Cast<object>().ToList(),
            ["repair"] = true
        }
    }, ct);

    return Results.Ok(new { queued = docIds.Count, jobId });
})
.RequireRateLimiting("write");

// ═════════════════════════════════════════════════════════════════════════════
// Start
// ═════════════════════════════════════════════════════════════════════════════

try
{
    // Resolve at startup to fail fast when users are not configured in non-development environments.
    using (var scope = app.Services.CreateScope())
    {
        _ = scope.ServiceProvider.GetRequiredService<IUserCredentialStore>();
    }

    await app.RunAsync();
}
finally
{
    await Log.CloseAndFlushAsync();
}

// ═════════════════════════════════════════════════════════════════════════════
// Type Declarations (must be at the end for top-level statements)
// ═════════════════════════════════════════════════════════════════════════════

// Tornar o Program acessível para testes de integração
public partial class Program { }
