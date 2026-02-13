using Gabi.Api;
using Gabi.Postgres;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Gabi.Api.Tests;

public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        
        // Configurar JWT e Users para testes
        builder.ConfigureAppConfiguration((context, config) =>
        {
            var testConfig = new Dictionary<string, string?>
            {
                ["Jwt:Key"] = "test-key-minimum-32-characters-long-for-testing-only!",
                ["Jwt:Issuer"] = "GabiApiTest",
                ["Jwt:Audience"] = "GabiDashboardTest",
                ["Jwt:ExpiryHours"] = "1",
                ["Users:0:Username"] = "admin",
                ["Users:0:Password"] = "admin123",
                ["Users:0:Role"] = "Admin",
                ["Users:1:Username"] = "operator",
                ["Users:1:Password"] = "operator123",
                ["Users:1:Role"] = "Operator",
                ["Users:2:Username"] = "viewer",
                ["Users:2:Password"] = "viewer123",
                ["Users:2:Role"] = "Viewer",
                ["Cors:AllowedOrigins:0"] = "http://localhost:3000"
            };
            
            config.AddInMemoryCollection(testConfig);
        });
        
        builder.ConfigureServices(services =>
        {
            // Remover DbContext real
            var descriptor = services.SingleOrDefault(
                d => d.ServiceType == typeof(DbContextOptions<GabiDbContext>));
            if (descriptor != null)
                services.Remove(descriptor);

            // Usar InMemory database para testes
            services.AddDbContext<GabiDbContext>(options =>
            {
                options.UseInMemoryDatabase("GabiTestDb");
            });

            // Remover RateLimiter para testes (evita 429 Too Many Requests)
            var rateLimiterDescriptor = services.SingleOrDefault(
                d => d.ServiceType.FullName?.Contains("RateLimiter") == true ||
                     d.ImplementationType?.FullName?.Contains("RateLimiter") == true);
            if (rateLimiterDescriptor != null)
                services.Remove(rateLimiterDescriptor);

            // Build service provider para inicializar o banco
            var sp = services.BuildServiceProvider();
            using var scope = sp.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            db.Database.EnsureCreated();
        });
    }
}
