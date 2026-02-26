using System.Text.Json;
using Gabi.Api;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Index;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Ingest;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Hangfire;
using Hangfire.PostgreSql;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Gabi.System.Tests.Security;

namespace Gabi.System.Tests;

/// <summary>
/// WebApplicationFactory for Zero-Kelvin: uses real Postgres and Redis URLs from EnvironmentManager (no InMemory).
/// Includes an embedded Hangfire server so that enqueued jobs are actually processed in-process.
/// </summary>
public sealed class ZeroKelvinWebApplicationFactory : WebApplicationFactory<Program>
{
    private readonly string _connectionString;
    private readonly string _redisUrl;

    private readonly string? _sourcesPath;

    public ZeroKelvinWebApplicationFactory(string connectionString, string redisUrl, string? sourcesPath = null)
    {
        _connectionString = connectionString;
        _redisUrl = redisUrl;
        _sourcesPath = sourcesPath;
    }

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");

        builder.ConfigureAppConfiguration((_, config) =>
        {
            config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Default"] = _connectionString,
                ["Gabi:RedisUrl"] = _redisUrl,
                ["GABI_EMBEDDINGS_URL"] = "",
                ["Jwt:Key"] = "test-key-minimum-32-characters-long-for-testing-only!",
                ["Jwt:Issuer"] = "GabiApiTest",
                ["Jwt:Audience"] = "GabiDashboardTest",
                ["Jwt:ExpiryHours"] = "1",
                ["GABI_USERS"] = BuildUsersJson(),
                ["Cors:AllowedOrigins:0"] = "http://localhost:5173",
                ["GABI_MEDIA_ALLOW_LOCAL_FILE"] = "true",
                ["Gabi:Media:BasePath"] = "/tmp/gabi-zero-kelvin/workspace",
                ["Gabi:Media:AllowedUrlPatterns:0"] = "https://*.gov.br/*",
                ["Gabi:Fetch:AllowedUrlPatterns:0"] = "https://*.gov.br/*",
                ["GABI_SOURCES_PATH"] = _sourcesPath ?? "",
            });
        });

        builder.ConfigureServices(services =>
        {
            var descriptor = services.SingleOrDefault(d => d.ServiceType == typeof(DbContextOptions<GabiDbContext>));
            if (descriptor != null)
                services.Remove(descriptor);

            services.AddDbContext<GabiDbContext>(options => options.UseNpgsql(_connectionString));

            // Garantir Hangfire no teste (API só registra se ConnectionString estiver setada no build)
            if (services.All(x => x.ServiceType != typeof(Hangfire.IBackgroundJobClient)))
            {
                services.AddHangfire(config => config
                    .SetDataCompatibilityLevel(Hangfire.CompatibilityLevel.Version_180)
                    .UseSimpleAssemblyNameTypeSerializer()
                    .UseRecommendedSerializerSettings()
                    .UsePostgreSqlStorage(
                        _connectionString,
                        new PostgreSqlStorageOptions
                        {
                            QueuePollInterval = TimeSpan.FromSeconds(5),
                            InvisibilityTimeout = TimeSpan.FromMinutes(10),
                            UseSlidingInvisibilityTimeout = true
                        }));
            }

            // Embedded Hangfire server: processes all queues so pipeline phases actually run in-process
            services.AddHangfireServer(options =>
            {
                options.ServerName = "zero-kelvin";
                options.WorkerCount = 2;
                options.Queues = new[] { "seed", "discovery", "fetch", "ingest", "embed", "default" };
            });

            // Replace StubGabiJobRunner with the real Worker implementation
            var stub = services.SingleOrDefault(d => d.ServiceType == typeof(IGabiJobRunner));
            if (stub != null) services.Remove(stub);
            services.AddScoped<IGabiJobRunner, GabiJobRunner>();

            // Job executors
            services.AddScoped<IJobExecutor, CatalogSeedJobExecutor>();
            services.AddScoped<IJobExecutor, SourceDiscoveryJobExecutor>();
            services.AddScoped<IJobExecutor, FetchJobExecutor>();
            services.AddScoped<IJobExecutor, IngestJobExecutor>();
            services.AddScoped<IJobExecutor, EmbedAndIndexJobExecutor>();

            // Discovery engine (for SourceDiscoveryJobExecutor)
            if (services.All(x => x.ServiceType != typeof(DiscoveryAdapterRegistry)))
            {
                services.AddSingleton<IDiscoveryAdapter, StaticUrlDiscoveryAdapter>();
                services.AddSingleton<IDiscoveryAdapter, UrlPatternDiscoveryAdapter>();
                services.AddSingleton<DiscoveryAdapterRegistry>();
                services.AddSingleton<SourceCatalogStrategyValidator>();
                services.AddSingleton<DiscoveryEngine>();
            }

            // Fetch URL validator
            if (services.All(x => x.ServiceType != typeof(IFetchUrlValidator)))
            {
                services.AddSingleton<Gabi.Worker.Security.FetchUrlValidator>();
                services.AddSingleton<IFetchUrlValidator>(sp => sp.GetRequiredService<Gabi.Worker.Security.FetchUrlValidator>());
            }

            // Normalizer + chunker for IngestJobExecutor / EmbedAndIndexJobExecutor
            if (services.All(x => x.ServiceType != typeof(ICanonicalDocumentNormalizer)))
                services.AddSingleton<ICanonicalDocumentNormalizer, CanonicalDocumentNormalizer>();
            if (services.All(x => x.ServiceType != typeof(IChunker)))
                services.AddSingleton<IChunker, FixedSizeChunker>();

            // Embedder fallback (no TEI URL in test → HashEmbedder)
            if (services.All(x => x.ServiceType != typeof(IEmbedder)))
                services.AddSingleton<IEmbedder, HashEmbedder>();

            // Document indexer fallback (no ES URL in test → LocalDocumentIndexer)
            if (services.All(x => x.ServiceType != typeof(IDocumentIndexer)))
                services.AddSingleton<IDocumentIndexer, LocalDocumentIndexer>();

            // Media projector (for IngestJobExecutor fan-out)
            if (services.All(x => x.ServiceType != typeof(IMediaTextProjector)))
                services.AddSingleton<IMediaTextProjector, MediaTextProjector>();

            // Document repository (for IngestJobExecutor writes — DEF-14)
            if (services.All(x => x.ServiceType != typeof(IDocumentRepository)))
                services.AddScoped<IDocumentRepository, DocumentRepository>();

            services.AddAuthentication(options =>
                {
                    options.DefaultAuthenticateScheme = TestAuthHandler.SchemeName;
                    options.DefaultChallengeScheme = TestAuthHandler.SchemeName;
                    options.DefaultScheme = TestAuthHandler.SchemeName;
                })
                .AddScheme<AuthenticationSchemeOptions, TestAuthHandler>(TestAuthHandler.SchemeName, _ => { });

            // Garantir schema no banco antes de qualquer request (mesmo connection string do env)
            services.AddSingleton<IHostedService, ZeroKelvinMigrateHostedService>(_ =>
                new ZeroKelvinMigrateHostedService(_connectionString));
        });
    }

    /// <summary>
    /// Aplica migrations no startup para garantir que source_pipeline_state e demais tabelas existam.
    /// </summary>
    private sealed class ZeroKelvinMigrateHostedService : IHostedService
    {
        private readonly string _connectionString;

        public ZeroKelvinMigrateHostedService(string connectionString) => _connectionString = connectionString;

        public Task StartAsync(CancellationToken ct)
        {
            var options = new DbContextOptionsBuilder<GabiDbContext>()
                .UseNpgsql(_connectionString)
                .Options;
            using var context = new GabiDbContext(options);
            context.Database.Migrate();
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken ct) => Task.CompletedTask;
    }

    public HttpClient CreateOperatorClient()
    {
        var client = CreateClient(new WebApplicationFactoryClientOptions
        {
            BaseAddress = new Uri("https://localhost"),
            AllowAutoRedirect = false
        });
        client.DefaultRequestHeaders.Add("X-Test-Role", "Operator");
        return client;
    }

    private static string BuildUsersJson()
    {
        var users = new[]
        {
            new { username = "admin", password_hash = BCrypt.Net.BCrypt.HashPassword("admin123"), role = "Admin" },
            new { username = "operator", password_hash = BCrypt.Net.BCrypt.HashPassword("op123"), role = "Operator" },
            new { username = "viewer", password_hash = BCrypt.Net.BCrypt.HashPassword("view123"), role = "Viewer" }
        };
        return JsonSerializer.Serialize(users);
    }
}
