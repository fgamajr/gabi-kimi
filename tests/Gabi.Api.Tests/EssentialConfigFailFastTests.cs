using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Hosting;
using Xunit;

namespace Gabi.Api.Tests;

/// <summary>
/// DEF-19: Fail-fast de configurações essenciais. Em Production, ausência de Jwt:Key deve lançar no Build().
/// </summary>
public class EssentialConfigFailFastTests
{
    [Fact]
    public void Build_WhenProductionAndJwtKeyMissing_ThrowsInvalidOperationException()
    {
        // WebApplication.CreateBuilder carrega config antes do ConfigureWebHost; usar env vars
        // para garantir ConnectionStrings presente e Jwt:Key ausente, de forma a falhar em JWT.
        var connectionStringBackup = Environment.GetEnvironmentVariable("ConnectionStrings__Default");
        var jwtKeyBackup = Environment.GetEnvironmentVariable("Jwt__Key");
        try
        {
            Environment.SetEnvironmentVariable("ConnectionStrings__Default", "Host=localhost;Port=5432;Database=gabi;Username=u;Password=p");
            Environment.SetEnvironmentVariable("Jwt__Key", null);

            using var factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            {
                builder.UseEnvironment(Environments.Production);
            });

            var ex = Assert.Throws<InvalidOperationException>(() => factory.CreateClient());
            Assert.Contains("Jwt:Key", ex.Message, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            RestoreEnv("ConnectionStrings__Default", connectionStringBackup);
            RestoreEnv("Jwt__Key", jwtKeyBackup);
        }
    }

    private static void RestoreEnv(string key, string? value)
    {
        if (value is null)
            Environment.SetEnvironmentVariable(key, null);
        else
            Environment.SetEnvironmentVariable(key, value);
    }
}
