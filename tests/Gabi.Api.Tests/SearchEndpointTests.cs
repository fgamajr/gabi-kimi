using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using FluentAssertions;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace Gabi.Api.Tests;

public class SearchEndpointTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly CustomWebApplicationFactory _factory;

    public SearchEndpointTests(CustomWebApplicationFactory factory)
    {
        _factory = factory;
    }

    [Fact]
    public async Task SearchEndpoint_ShouldReturnBadRequest_WhenQueryIsEmpty()
    {
        var client = await _factory.CreateAuthenticatedClientAsync("viewer", "viewer123");

        var response = await client.GetAsync("/api/v1/search?q=&page=1&pageSize=10");

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task SearchEndpoint_ShouldFilterBySource_AndReturnOnlyCompletedDocuments()
    {
        var sourceA = $"search-a-{Guid.NewGuid():N}";
        var sourceB = $"search-b-{Guid.NewGuid():N}";

        await _factory.EnsureSourceExistsAsync(sourceA);
        await _factory.EnsureSourceExistsAsync(sourceB);

        await using (var scope = _factory.Services.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

            var linkA = new DiscoveredLinkEntity
            {
                SourceId = sourceA,
                Url = $"https://example.org/{sourceA}",
                UrlHash = ComputeSha256($"https://example.org/{sourceA}"),
                Status = "completed",
                DiscoveryStatus = "completed",
                FetchStatus = "completed",
                IngestStatus = "completed",
                Metadata = "{}",
                CreatedBy = "test",
                UpdatedBy = "test"
            };

            var linkB = new DiscoveredLinkEntity
            {
                SourceId = sourceB,
                Url = $"https://example.org/{sourceB}",
                UrlHash = ComputeSha256($"https://example.org/{sourceB}"),
                Status = "completed",
                DiscoveryStatus = "completed",
                FetchStatus = "completed",
                IngestStatus = "completed",
                Metadata = "{}",
                CreatedBy = "test",
                UpdatedBy = "test"
            };

            db.DiscoveredLinks.AddRange(linkA, linkB);
            await db.SaveChangesAsync();

            db.Documents.AddRange(
                new DocumentEntity
                {
                    LinkId = linkA.Id,
                    SourceId = sourceA,
                    ExternalId = "doc-a-1",
                    DocumentId = "doc-a-1",
                    Title = "Acordao sobre licitacao",
                    Content = "Texto completo do acordao A.",
                    Status = "completed",
                    Metadata = "{}",
                    CreatedBy = "test",
                    UpdatedBy = "test"
                },
                new DocumentEntity
                {
                    LinkId = linkA.Id,
                    SourceId = sourceA,
                    ExternalId = "doc-a-2",
                    DocumentId = "doc-a-2",
                    Title = "Nota tecnica",
                    Content = "Documento sem o termo pesquisado.",
                    Status = "completed",
                    Metadata = "{}",
                    CreatedBy = "test",
                    UpdatedBy = "test"
                },
                new DocumentEntity
                {
                    LinkId = linkA.Id,
                    SourceId = sourceA,
                    ExternalId = "doc-a-3",
                    DocumentId = "doc-a-3",
                    Title = "Acordao com falha",
                    Content = "Este nao deve aparecer por status failed.",
                    Status = "failed",
                    Metadata = "{}",
                    CreatedBy = "test",
                    UpdatedBy = "test"
                },
                new DocumentEntity
                {
                    LinkId = linkB.Id,
                    SourceId = sourceB,
                    ExternalId = "doc-b-1",
                    DocumentId = "doc-b-1",
                    Title = "Acordao de outra fonte",
                    Content = "Nao deve aparecer com filtro de source.",
                    Status = "completed",
                    Metadata = "{}",
                    CreatedBy = "test",
                    UpdatedBy = "test"
                });

            await db.SaveChangesAsync();
        }

        var client = await _factory.CreateAuthenticatedClientAsync("viewer", "viewer123");
        var response = await client.GetAsync($"/api/v1/search?q=acordao&sourceId={sourceA}&page=1&pageSize=10");

        response.StatusCode.Should().Be(HttpStatusCode.OK);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        doc.RootElement.GetProperty("total").GetInt32().Should().Be(1);
        var hits = doc.RootElement.GetProperty("hits");
        hits.GetArrayLength().Should().Be(1);
        hits[0].GetProperty("sourceId").GetString().Should().Be(sourceA);
        hits[0].GetProperty("externalId").GetString().Should().Be("doc-a-1");
    }

    private static string ComputeSha256(string input)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
