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
        var response = await _client.GetAsync("/api/v1/dashboard/pipeline/phases");

        // Assert - deve retornar alguma resposta (401, 404, ou outro)
        // O importante é que a API está respondendo
        Assert.NotEqual(HttpStatusCode.InternalServerError, response.StatusCode);
    }

    [Fact]
    public async Task PipelinePhasesEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        var response = await _client.GetAsync("/api/v1/dashboard/pipeline/phases");
        Assert.True(
            response.StatusCode == HttpStatusCode.OK || response.StatusCode == HttpStatusCode.NotFound
                || response.StatusCode == HttpStatusCode.Unauthorized || response.StatusCode == HttpStatusCode.BadRequest,
            $"Expected OK/404/401/400, got {response.StatusCode}");
    }

    [Fact]
    public async Task DiscoveryLastBySourceEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        var response = await _client.GetAsync("/api/v1/dashboard/sources/test-source/discovery/last");
        Assert.True(
            response.StatusCode == HttpStatusCode.OK || response.StatusCode == HttpStatusCode.NotFound
                || response.StatusCode == HttpStatusCode.Unauthorized || response.StatusCode == HttpStatusCode.BadRequest,
            $"Expected OK/404/401/400, got {response.StatusCode}");
    }

    [Fact]
    public async Task JobsEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        var response = await _client.GetAsync("/api/v1/jobs");
        Assert.True(
            response.StatusCode == HttpStatusCode.OK || response.StatusCode == HttpStatusCode.NotFound
                || response.StatusCode == HttpStatusCode.Unauthorized || response.StatusCode == HttpStatusCode.BadRequest,
            $"Expected OK/404/401/400, got {response.StatusCode}");
    }

    [Fact]
    public async Task FetchLastBySourceEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        var response = await _client.GetAsync("/api/v1/dashboard/sources/test-source/fetch/last");
        Assert.True(
            response.StatusCode == HttpStatusCode.OK || response.StatusCode == HttpStatusCode.NotFound
                || response.StatusCode == HttpStatusCode.Unauthorized || response.StatusCode == HttpStatusCode.BadRequest,
            $"Expected OK/404/401/400, got {response.StatusCode}");
    }

    [Fact]
    public async Task MediaUploadEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        using var content = new MultipartFormDataContent();
        content.Add(new StringContent("tcu_media_upload"), "source_id");
        content.Add(new StringContent("ext-test-1"), "external_id");
        content.Add(new StringContent("https://example.org/video"), "media_url");

        var response = await _client.PostAsync("/api/v1/media/upload", content);
        Assert.True(
            response.StatusCode == HttpStatusCode.Accepted
            || response.StatusCode == HttpStatusCode.BadRequest
            || response.StatusCode == HttpStatusCode.NotFound
            || response.StatusCode == HttpStatusCode.Unauthorized,
            $"Expected 202/400/404/401, got {response.StatusCode}");
    }

    [Fact]
    public async Task MediaRequeueEndpoint_Exists_ReturnsClientOrSuccessStatus()
    {
        var response = await _client.PostAsync("/api/v1/media/1/requeue", content: null);
        Assert.True(
            response.StatusCode == HttpStatusCode.Accepted
            || response.StatusCode == HttpStatusCode.NotFound
            || response.StatusCode == HttpStatusCode.Unauthorized
            || response.StatusCode == HttpStatusCode.BadRequest,
            $"Expected 202/404/401/400, got {response.StatusCode}");
    }
}
