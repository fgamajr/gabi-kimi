using System.Text.Json;
using Gabi.Api;
using Gabi.Postgres;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Gabi.ReliabilityLab.Pipeline.Infrastructure;

public sealed class LabWebApplicationFactory : WebApplicationFactory<Program>
{
    private readonly string _connectionString;
    private readonly string _redisUrl;

    public LabWebApplicationFactory(string connectionString, string redisUrl)
    {
        _connectionString = connectionString;
        _redisUrl = redisUrl;
    }

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Development");
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
                ["Gabi:Media:BasePath"] = "/tmp/gabi-lab/workspace",
                ["Gabi:Media:AllowedUrlPatterns:0"] = "https://*.gov.br/*"
            });
        });
        builder.ConfigureServices(services =>
        {
            var descriptor = services.SingleOrDefault(d => d.ServiceType == typeof(DbContextOptions<GabiDbContext>));
            if (descriptor != null) services.Remove(descriptor);
            services.AddDbContext<GabiDbContext>(options => options.UseNpgsql(_connectionString));
            services.AddAuthentication(options =>
            {
                options.DefaultAuthenticateScheme = LabTestAuthHandler.SchemeName;
                options.DefaultChallengeScheme = LabTestAuthHandler.SchemeName;
                options.DefaultScheme = LabTestAuthHandler.SchemeName;
            }).AddScheme<AuthenticationSchemeOptions, LabTestAuthHandler>(LabTestAuthHandler.SchemeName, _ => { });
        });
    }

    public HttpClient CreateOperatorClient()
    {
        var client = CreateClient(new WebApplicationFactoryClientOptions { BaseAddress = new Uri("https://localhost"), AllowAutoRedirect = false });
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
