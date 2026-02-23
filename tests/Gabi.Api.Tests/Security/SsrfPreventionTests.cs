using System.Net;
using Xunit;

namespace Gabi.Api.Tests.Security;

public class SsrfPreventionTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly CustomWebApplicationFactory _factory;

    public SsrfPreventionTests(CustomWebApplicationFactory factory)
    {
        _factory = factory;
    }

    [Fact]
    public async Task Upload_WithPrivateIp_Returns400()
    {
        var response = await UploadAsync("http://127.0.0.1/video.mp4");
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Upload_WithMetadataEndpoint_Returns400()
    {
        var response = await UploadAsync("http://169.254.169.254/latest/meta-data/");
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Upload_WithAllowedUrl_Returns200()
    {
        var response = await UploadAsync("https://www.youtube.com/watch?v=test");
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.Accepted, $"Expected 202 but got {(int)response.StatusCode}: {body}");
    }

    [Fact]
    public async Task Upload_WithHostnameResolvingToPrivateIp_Returns400()
    {
        var response = await UploadAsync("http://localhost/internal");
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    private async Task<HttpResponseMessage> UploadAsync(string mediaUrl)
    {
        await _factory.EnsureSourceExistsAsync();
        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");

        using var content = new MultipartFormDataContent();
        content.Add(new StringContent("tcu_media_upload"), "source_id");
        content.Add(new StringContent(Guid.NewGuid().ToString("N")), "external_id");
        content.Add(new StringContent(mediaUrl), "media_url");

        return await client.PostAsync("/api/v1/media/upload", content);
    }
}
