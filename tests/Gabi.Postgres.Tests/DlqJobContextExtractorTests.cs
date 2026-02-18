using System.Text.Json;
using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

public class DlqJobContextExtractorTests
{
    [Fact]
    public void Extract_RunAsyncArgumentsShape_ShouldCaptureSourceAndOriginalJobId()
    {
        var originalJobId = Guid.NewGuid();
        var args = new object?[]
        {
            originalJobId,
            "source_discovery",
            "zz_dlq_probe",
            "{\"force\":true,\"year\":null}",
            CancellationToken.None
        };

        var ctx = DlqJobContextExtractor.Extract(args);

        Assert.Equal("zz_dlq_probe", ctx.SourceId);
        Assert.Equal(originalJobId, ctx.OriginalJobId);
        Assert.NotNull(ctx.Payload);
        using var payloadDoc = JsonDocument.Parse(ctx.Payload!);
        Assert.Equal(JsonValueKind.Object, payloadDoc.RootElement.ValueKind);
        Assert.True(payloadDoc.RootElement.GetProperty("force").GetBoolean());
    }

    [Fact]
    public void Extract_LegacyJsonElementPayload_ShouldCaptureSourceAndOriginalJobId()
    {
        var originalJobId = Guid.NewGuid();
        using var doc = JsonDocument.Parse($$"""
            {
              "SourceId": "legacy_source",
              "JobId": "{{originalJobId}}",
              "foo": 123
            }
            """);
        var args = new object?[] { doc.RootElement.Clone() };

        var ctx = DlqJobContextExtractor.Extract(args);

        Assert.Equal("legacy_source", ctx.SourceId);
        Assert.Equal(originalJobId, ctx.OriginalJobId);
        Assert.NotNull(ctx.Payload);
        using var payloadDoc = JsonDocument.Parse(ctx.Payload!);
        Assert.Equal(123, payloadDoc.RootElement.GetProperty("foo").GetInt32());
    }
}
