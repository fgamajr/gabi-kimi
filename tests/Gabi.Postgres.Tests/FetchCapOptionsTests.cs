using System.Text.Json;
using Gabi.Postgres;
using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

public class FetchCapOptionsTests
{
    [Fact]
    public void ResolveMaxFieldLength_PrefersParseConfigLimit()
    {
        var parseConfig = JsonDocument.Parse("{\"limits\":{\"max_field_chars\":4096}}").RootElement;

        var value = FetchJobExecutor.ResolveMaxFieldLength(parseConfig, envValue: "2048");

        Assert.Equal(4096, value);
    }

    [Fact]
    public void ResolveMaxFieldLength_FallsBackToEnvThenDefault()
    {
        var withEnv = FetchJobExecutor.ResolveMaxFieldLength(parseConfig: null, envValue: "8192");
        var withDefault = FetchJobExecutor.ResolveMaxFieldLength(parseConfig: null, envValue: "abc");

        Assert.Equal(8192, withEnv);
        Assert.Equal(FetchJobExecutor.DefaultMaxFieldLength, withDefault);
    }

    [Fact]
    public void ReadMaxDocsPerSource_FromPayloadVariants_ParsesPositiveValues()
    {
        var fromInt = new Dictionary<string, object> { ["max_docs_per_source"] = 20000 };
        var fromString = new Dictionary<string, object> { ["max_docs_per_source"] = "1500" };
        var fromJsonNumber = new Dictionary<string, object>
        {
            ["max_docs_per_source"] = JsonDocument.Parse("200").RootElement.Clone()
        };

        Assert.Equal(20000, FetchJobExecutor.ReadMaxDocsPerSource(fromInt));
        Assert.Equal(1500, FetchJobExecutor.ReadMaxDocsPerSource(fromString));
        Assert.Equal(200, FetchJobExecutor.ReadMaxDocsPerSource(fromJsonNumber));
    }

    [Fact]
    public void ReadMaxDocsPerSource_NonPositiveOrInvalid_ReturnsNull()
    {
        var zero = new Dictionary<string, object> { ["max_docs_per_source"] = 0 };
        var negative = new Dictionary<string, object> { ["max_docs_per_source"] = -1 };
        var invalid = new Dictionary<string, object> { ["max_docs_per_source"] = "abc" };

        Assert.Null(FetchJobExecutor.ReadMaxDocsPerSource(zero));
        Assert.Null(FetchJobExecutor.ReadMaxDocsPerSource(negative));
        Assert.Null(FetchJobExecutor.ReadMaxDocsPerSource(invalid));
    }

    [Theory]
    [InlineData(19999, 20000, false)]
    [InlineData(20000, 20000, true)]
    [InlineData(21000, 20000, true)]
    public void IsCapReached_UsesInclusiveBoundary(int docsCreated, int maxDocs, bool expected)
    {
        Assert.Equal(expected, FetchJobExecutor.IsCapReached(docsCreated, maxDocs));
    }

    [Fact]
    public void ParsePayload_FromHangfireStoredShape_ExtractsCap()
    {
        const string payloadJson = "{\"phase\":\"fetch\",\"max_docs_per_source\":20000}";
        var payload = JobPayloadParser.ParsePayload(payloadJson);
        Assert.True(payload.Count > 0);
        Assert.True(
            payload.ContainsKey("max_docs_per_source"),
            $"Payload keys: {string.Join(',', payload.Keys)}");

        var maxDocs = FetchJobExecutor.ReadMaxDocsPerSource(payload);

        Assert.Equal(20000, maxDocs);
    }
}
