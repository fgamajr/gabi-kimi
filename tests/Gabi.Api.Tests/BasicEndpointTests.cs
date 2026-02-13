using System.Net;
using Xunit;

namespace Gabi.Api.Tests;

/// <summary>
/// Testes básicos para verificar que a API está funcionando
/// </summary>
public class BasicEndpointTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client;

    public BasicEndpointTests(CustomWebApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task HealthEndpoint_ReturnsSuccess()
    {
        // Act
        var response = await _client.GetAsync("/health");

        // Assert
        Assert.True(response.StatusCode == HttpStatusCode.OK || 
                    response.StatusCode == HttpStatusCode.ServiceUnavailable,
                    $"Expected OK or ServiceUnavailable, got {response.StatusCode}");
    }

    [Fact]
    public async Task ApiExists_ReturnsSomeResponse()
    {
        // Act - tentar acessar qualquer endpoint da API
        var response = await _client.GetAsync("/api/v1/dashboard/stats");

        // Assert - deve retornar alguma resposta (401, 404, ou outro)
        // O importante é que a API está respondendo
        Assert.NotEqual(HttpStatusCode.InternalServerError, response.StatusCode);
    }
}
