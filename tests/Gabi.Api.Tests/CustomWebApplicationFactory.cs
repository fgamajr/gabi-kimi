using System.Text.Json;
using Gabi.Api;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Gabi.Api.Tests.Security;

namespace Gabi.Api.Tests;

public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    private readonly string _dbName = $"GabiTestDb_{Guid.NewGuid():N}";

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");

        builder.ConfigureAppConfiguration((context, config) =>
        {
            var testConfig = new Dictionary<string, string?>
            {
                ["Jwt:Key"] = "test-key-minimum-32-characters-long-for-testing-only!",
                ["Jwt:Issuer"] = "GabiApiTest",
                ["Jwt:Audience"] = "GabiDashboardTest",
                ["Jwt:ExpiryHours"] = "1",
                ["GABI_USERS"] = BuildUsersJson(),
                ["Cors:AllowedOrigins:0"] = "http://localhost:5173",
                ["GABI_MEDIA_ALLOW_LOCAL_FILE"] = "true",
                ["Gabi:Media:AllowLocalFile"] = "true",
                ["Gabi:Media:BasePath"] = "/tmp/gabi-security-tests/workspace",
                ["Gabi:Media:AllowedUrlPatterns:0"] = "https://*.youtube.com/*",
                ["Gabi:Media:AllowedUrlPatterns:1"] = "https://*.gov.br/*",
                ["Gabi:Media:AllowedUrlPatterns:2"] = "https://*.leg.br/*"
            };

            config.AddInMemoryCollection(testConfig);
        });

        builder.ConfigureServices(services =>
        {
            var descriptor = services.SingleOrDefault(
                d => d.ServiceType == typeof(DbContextOptions<GabiDbContext>));
            if (descriptor != null)
                services.Remove(descriptor);

            services.AddDbContext<GabiDbContext>(options =>
            {
                options.UseInMemoryDatabase(_dbName);
            });

            var jobQueueDescriptors = services
                .Where(d => d.ServiceType == typeof(IJobQueueRepository) ||
                            d.ImplementationType?.Name?.Contains("HangfireJobQueueRepository", StringComparison.Ordinal) == true)
                .ToList();
            foreach (var descriptorToRemove in jobQueueDescriptors)
                services.Remove(descriptorToRemove);
            services.AddScoped<IJobQueueRepository, FakeJobQueueRepository>();

            services.AddAuthentication(options =>
                {
                    options.DefaultAuthenticateScheme = TestAuthHandler.SchemeName;
                    options.DefaultChallengeScheme = TestAuthHandler.SchemeName;
                    options.DefaultScheme = TestAuthHandler.SchemeName;
                })
                .AddScheme<AuthenticationSchemeOptions, TestAuthHandler>(TestAuthHandler.SchemeName, _ => { });

            var sp = services.BuildServiceProvider();
            using var scope = sp.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            db.Database.EnsureCreated();
        });
    }

    public async Task EnsureSourceExistsAsync(string sourceId = "tcu_media_upload")
    {
        using var scope = Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var exists = await db.SourceRegistries.AnyAsync(s => s.Id == sourceId);
        if (exists)
            return;

        db.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Test Source",
            Provider = "test",
            DiscoveryStrategy = "static_url",
            DiscoveryConfig = "{}",
            Enabled = true
        });

        await db.SaveChangesAsync();
    }

    /// <summary>Ensures a source exists with PipelineConfig containing coverage.strict = true (for strict-coverage fallback tests).</summary>
    public async Task EnsureSourceWithStrictPipelineConfigAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var existing = await db.SourceRegistries.FindAsync(new object[] { sourceId }, ct);
        var pipelineConfig = """{"coverage":{"strict":true},"ingest":{"readiness":"text_ready"}}""";
        if (existing != null)
        {
            existing.PipelineConfig = pipelineConfig;
            db.SourceRegistries.Update(existing);
        }
        else
        {
            db.SourceRegistries.Add(new SourceRegistryEntity
            {
                Id = sourceId,
                Name = "Strict Source",
                Provider = "test",
                DiscoveryStrategy = "static_url",
                DiscoveryConfig = "{}",
                PipelineConfig = pipelineConfig,
                Enabled = true
            });
        }
        await db.SaveChangesAsync(ct);
    }

    public Task<HttpClient> CreateAuthenticatedClientAsync(string username, string password)
    {
        var client = CreateClient(new WebApplicationFactoryClientOptions
        {
            BaseAddress = new Uri("https://localhost"),
            AllowAutoRedirect = false
        });

        var role = username.Equals("admin", StringComparison.OrdinalIgnoreCase) ? "Admin"
            : username.Equals("operator", StringComparison.OrdinalIgnoreCase) ? "Operator"
            : "Viewer";
        client.DefaultRequestHeaders.Add("X-Test-Role", role);
        return Task.FromResult(client);
    }

    private static string BuildUsersJson()
    {
        var users = new[]
        {
            new { username = "admin", password_hash = BCrypt.Net.BCrypt.HashPassword("admin123"), role = "Admin" },
            new { username = "operator", password_hash = BCrypt.Net.BCrypt.HashPassword("operator123"), role = "Operator" },
            new { username = "viewer", password_hash = BCrypt.Net.BCrypt.HashPassword("viewer123"), role = "Viewer" }
        };

        return JsonSerializer.Serialize(users);
    }

}
