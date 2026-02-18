using Gabi.Api;
using Gabi.Api.Configuration;
using Gabi.Api.Middleware;
using Gabi.Api.Services;
using Gabi.Contracts.Api;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Jobs;
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
using Hangfire.PostgreSql;

var builder = WebApplication.CreateBuilder(args);

// Serilog: em Produção, JSON no console (Fly logs); em Dev, formato legível via appsettings
builder.Host.UseSerilog((context, _, configuration) =>
{
    configuration.ReadFrom.Configuration(context.Configuration);
    if (context.HostingEnvironment.IsProduction())
        configuration.WriteTo.Console(new CompactJsonFormatter());
});

// Database
var connectionString = builder.Configuration.GetConnectionString("Default");
if (!string.IsNullOrWhiteSpace(connectionString))
{
    builder.Services.AddDbContext<GabiDbContext>(options =>
        options.UseNpgsql(connectionString));
}

// Security Configuration
builder.Services.AddJwtAuthentication(builder.Configuration);
builder.Services.AddAuthorizationPolicies();
builder.Services.AddRateLimitingConfig();
builder.Services.AddCorsConfig(builder.Configuration, builder.Environment);

// Services
builder.Services.AddScoped<IJwtTokenService, JwtTokenService>();

// Hangfire (enqueue + dashboard; Worker processa com Hangfire Server)
if (!string.IsNullOrWhiteSpace(connectionString))
{
    builder.Services.AddHangfire(config => config
        .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
        .UseSimpleAssemblyNameTypeSerializer()
        .UseRecommendedSerializerSettings()
        .UsePostgreSqlStorage(
            connectionString,
            new PostgreSqlStorageOptions
            {
                QueuePollInterval = TimeSpan.FromSeconds(5),
                InvisibilityTimeout = TimeSpan.FromMinutes(10),
                UseSlidingInvisibilityTimeout = true
            }));
}

// Repositories
builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();
builder.Services.AddScoped<HangfireJobQueueRepository>();
builder.Services.AddScoped<IJobQueueRepository>(sp => sp.GetRequiredService<HangfireJobQueueRepository>());

// Stub for Hangfire job serialization (Worker executes the real implementation)
builder.Services.AddScoped<IGabiJobRunner, Gabi.Api.Jobs.StubGabiJobRunner>();

// Source Catalog Service (PostgreSQL version)
builder.Services.AddSingleton<ISourceCatalog>(sp =>
{
    var logger = sp.GetRequiredService<ILogger<PostgreSqlSourceCatalogService>>();
    var config = sp.GetRequiredService<IConfiguration>();
    var env = sp.GetRequiredService<IHostEnvironment>();
    return new PostgreSqlSourceCatalogService(sp, logger, config, env);
});

// Dashboard Service
builder.Services.AddScoped<IDashboardService, DashboardService>();

// DLQ Service
builder.Services.AddScoped<IDlqService, DlqService>();

// Health checks
var healthBuilder = builder.Services.AddHealthChecks()
    .AddCheck("self", () => HealthCheckResult.Healthy(), tags: new[] { "live" });

if (!string.IsNullOrWhiteSpace(connectionString))
    healthBuilder.AddNpgSql(connectionString, name: "postgres", tags: new[] { "ready" });

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

// 5. Rate Limiting (antes de auth para proteger contra brute force)
app.UseRateLimiter();

// 6. Request Size Limit
app.Use(async (context, next) =>
{
    // Limitar tamanho do request body (10MB)
    var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
    if (feature != null)
    {
        feature.MaxRequestBodySize = 10 * 1024 * 1024;
    }
    await next();
});

// 7. Authentication
app.UseAuthentication();

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
    IConfiguration config,
    CancellationToken ct) =>
{
    // Validar credenciais contra appsettings
    var users = config.GetSection("Users").Get<List<AppUser>>();
    var user = users?.FirstOrDefault(u => 
        u.Username == request.Username && u.Password == request.Password);
    
    if (user == null)
    {
        return Results.Unauthorized();
    }
    
    var token = tokenService.GenerateToken(user.Username, user.Role);
    return Results.Ok(new LoginResponse(true, token, null, user.Role));
})
.RequireRateLimiting("auth");

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

// POST /api/v1/sources/{sourceId}/refresh - Refresh source discovery (enqueues job)
app.MapPost(ApiRoutes.SourceRefresh, [Authorize(Policy = "RequireOperator")] async (string sourceId, ISourceCatalog catalog, CancellationToken ct) =>
{
    try
    {
        var result = await catalog.RefreshSourceAsync(sourceId, ct);
        return Results.Ok(new ApiEnvelope<RefreshResult>(result));
    }
    catch (KeyNotFoundException)
    {
        return Results.NotFound(new ApiError("SOURCE_NOT_FOUND", $"Source '{sourceId}' not found"));
    }
})
.RequireRateLimiting("write");

// ═════════════════════════════════════════════════════════════════════════════
// Jobs API (protegidos)
// ═════════════════════════════════════════════════════════════════════════════

// GET /api/v1/jobs - List sync jobs + elastic indexes (dashboard)
app.MapGet(ApiRoutes.Jobs, [Authorize(Policy = "RequireViewer")] async (ISourceCatalog catalog, CancellationToken ct) =>
{
    var jobs = await catalog.ListSyncJobsAsync(ct);
    return Results.Ok(new ApiEnvelope<JobsResponseDto>(jobs));
})
.RequireRateLimiting("read");

// GET /api/v1/stats - Dashboard stats (sources, total docs, elasticsearch)
app.MapGet(ApiRoutes.Stats, [Authorize(Policy = "RequireViewer")] async (ISourceCatalog catalog, CancellationToken ct) =>
{
    var stats = await catalog.GetSystemStatsAsync(ct);
    return Results.Ok(new ApiEnvelope<SystemStatsDto>(stats));
})
.RequireRateLimiting("read");

// GET /api/v1/pipeline - Pipeline stages (harvest, sync, ingest, index)
app.MapGet(ApiRoutes.Pipeline, [Authorize(Policy = "RequireViewer")] async (ISourceCatalog catalog, CancellationToken ct) =>
{
    var stages = await catalog.GetPipelineStagesAsync(ct);
    return Results.Ok(new ApiEnvelope<IReadOnlyList<PipelineStageDto>>(stages));
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

// ═════════════════════════════════════════════════════════════════════════════
// Dashboard API (Frontend-compatible endpoints) - Protegidos
// ═════════════════════════════════════════════════════════════════════════════

// GET /api/v1/dashboard/stats - Dashboard stats (matches React frontend contract)
app.MapGet("/api/v1/dashboard/stats", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var stats = await dashboard.GetStatsAsync(ct);
    return Results.Ok(stats);
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/jobs - Jobs list (matches React frontend contract)
app.MapGet("/api/v1/dashboard/jobs", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var jobs = await dashboard.GetJobsAsync(ct);
    return Results.Ok(jobs);
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/pipeline - Pipeline stages (matches React frontend contract)
app.MapGet("/api/v1/dashboard/pipeline", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var pipeline = await dashboard.GetPipelineAsync(ct);
    return Results.Ok(pipeline);
})
.RequireRateLimiting("read");

// GET /api/v1/dashboard/health - System health status
app.MapGet("/api/v1/dashboard/health", [Authorize(Policy = "RequireViewer")] async (IDashboardService dashboard, CancellationToken ct) =>
{
    var health = await dashboard.GetSystemHealthAsync(ct);
    return Results.Ok(health);
})
.RequireRateLimiting("read");

// POST /api/v1/dashboard/sources/{sourceId}/refresh - Refresh source (body optional; empty => Force = true)
app.MapPost("/api/v1/dashboard/sources/{sourceId}/refresh", [Authorize(Policy = "RequireOperator")] async (
    string sourceId,
    RefreshSourceRequest? request,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    var req = request ?? new RefreshSourceRequest { Force = true };
    var result = await dashboard.RefreshSourceAsync(sourceId, req, ct);
    return result.Success 
        ? Results.Ok(result)
        : Results.NotFound(result);
})
.RequireRateLimiting("write");

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
app.MapPost("/api/v1/dashboard/sources/{sourceId}/phases/{phase}", [Authorize(Policy = "RequireOperator")] async (
    string sourceId,
    string phase,
    StartPhaseRequest? request,
    IDashboardService dashboard,
    CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(phase) || !new[] { "discovery", "fetch", "ingest" }.Contains(phase.ToLowerInvariant()))
        return Results.BadRequest(new { error = "phase must be discovery, fetch, or ingest" });
    var result = await dashboard.StartPhaseAsync(sourceId, phase, request, ct);
    return result.Success ? Results.Ok(result) : Results.NotFound(result);
})
.RequireRateLimiting("write");

// GET /api/v1/dashboard/safra - Safra details (matches React frontend contract)
app.MapGet("/api/v1/dashboard/safra", [Authorize(Policy = "RequireViewer")] async (string? sourceId, IDashboardService dashboard, CancellationToken ct) =>
{
    var safra = await dashboard.GetSafraAsync(sourceId, ct);
    return Results.Ok(safra);
})
.RequireRateLimiting("read");

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
        return Results.NotFound(new { error = $"Source '{sourceId}' not found" });
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

// ═════════════════════════════════════════════════════════════════════════════
// Start
// ═════════════════════════════════════════════════════════════════════════════

try
{
    await app.RunAsync();
}
finally
{
    await Log.CloseAndFlushAsync();
}

// ═════════════════════════════════════════════════════════════════════════════
// Type Declarations (must be at the end for top-level statements)
// ═════════════════════════════════════════════════════════════════════════════

// Modelo para usuário em appsettings
public record AppUser(string Username, string Password, string Role);

// Tornar o Program acessível para testes de integração
public partial class Program { }
