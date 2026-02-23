using System.Net;
using System.Net.Http.Json;
using Xunit;

namespace Gabi.Api.Tests.Security;

public class PathTraversalTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly CustomWebApplicationFactory _factory;
    private static readonly string BasePath = Path.Combine(Path.GetTempPath(), "gabi-security-tests", "workspace");

    public PathTraversalTests(CustomWebApplicationFactory factory)
    {
        _factory = factory;
    }

    [Fact]
    public async Task LocalFile_WithTraversalAttack_Returns400()
    {
        await _factory.EnsureSourceExistsAsync();
        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");

        var payload = new
        {
            sourceId = "tcu_media_upload",
            externalId = $"ext-{Guid.NewGuid():N}",
            filePath = "/workspace/../../../etc/passwd"
        };

        var response = await client.PostAsJsonAsync("/api/v1/media/local-file", payload);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task LocalFile_WithSymlinkOutsideWorkspace_Returns400()
    {
        await _factory.EnsureSourceExistsAsync();
        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");

        Directory.CreateDirectory(BasePath);
        var outsideFile = Path.Combine(Path.GetTempPath(), "gabi-security-tests", "outside.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(outsideFile)!);
        await File.WriteAllTextAsync(outsideFile, "outside");

        var symlinkPath = Path.Combine(BasePath, $"link-{Guid.NewGuid():N}.txt");
        if (File.Exists(symlinkPath))
            File.Delete(symlinkPath);

        File.CreateSymbolicLink(symlinkPath, outsideFile);

        var payload = new
        {
            sourceId = "tcu_media_upload",
            externalId = $"ext-{Guid.NewGuid():N}",
            filePath = symlinkPath
        };

        var response = await client.PostAsJsonAsync("/api/v1/media/local-file", payload);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task LocalFile_WithValidPath_Returns200()
    {
        await _factory.EnsureSourceExistsAsync();
        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");

        Directory.CreateDirectory(BasePath);
        var validFile = Path.Combine(BasePath, $"media-{Guid.NewGuid():N}.txt");
        await File.WriteAllTextAsync(validFile, "ok");

        var payload = new
        {
            sourceId = "tcu_media_upload",
            externalId = $"ext-{Guid.NewGuid():N}",
            filePath = validFile
        };

        var response = await client.PostAsJsonAsync("/api/v1/media/local-file", payload);
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.Accepted, $"Expected 202 but got {(int)response.StatusCode}: {body}");
    }
}
