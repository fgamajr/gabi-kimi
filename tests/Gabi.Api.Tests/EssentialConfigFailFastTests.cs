using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Hosting;
using Xunit;

namespace Gabi.Api.Tests;

/// <summary>
/// DEF-19: Fail-fast de configurações essenciais. Em Production, ausência de Jwt:Key deve lançar no Build().
/// </summary>
[Collection("Api")]
public class EssentialConfigFailFastTests
{
    [Fact]
    public void Build_WhenProductionAndJwtKeyMissing_ThrowsInvalidOperationException()
    {
        // WebApplication.CreateBuilder carrega config antes do ConfigureWebHost; usar env vars
        // para garantir ConnectionStrings presente e Jwt:Key ausente, de forma a falhar em JWT.
        var connectionStringBackup = Environment.GetEnvironmentVariable("ConnectionStrings__Default");
        var jwtKeyBackup = Environment.GetEnvironmentVariable("Jwt__Key");
        var embeddingsUrlBackup = Environment.GetEnvironmentVariable("GABI_EMBEDDINGS_URL");
        try
        {
            Environment.SetEnvironmentVariable("ConnectionStrings__Default", "Host=localhost;Port=5432;Database=gabi;Username=u;Password=p");
            // Provide GABI_EMBEDDINGS_URL so the embeddings guard passes and the JWT guard is reached (DEF-19).
            Environment.SetEnvironmentVariable("GABI_EMBEDDINGS_URL", "http://tei:80");
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
            RestoreEnv("GABI_EMBEDDINGS_URL", embeddingsUrlBackup);
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
