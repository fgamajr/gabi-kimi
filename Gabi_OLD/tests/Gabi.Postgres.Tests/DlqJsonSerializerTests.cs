using System.Text.Json;
using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

public class DlqJsonSerializerTests
{
    [Fact]
    public void SerializeStackTrace_MultilineText_ProducesValidJsonObject()
    {
        var stackTrace = "line 1\nline 2\nline 3";

        var json = DlqJsonSerializer.SerializeStackTrace(stackTrace);

        Assert.NotNull(json);
        using var doc = JsonDocument.Parse(json!);
        Assert.Equal(JsonValueKind.Object, doc.RootElement.ValueKind);
        Assert.Equal(stackTrace, doc.RootElement.GetProperty("text").GetString());
        Assert.Equal(3, doc.RootElement.GetProperty("lines").GetArrayLength());
    }

    [Fact]
    public void SerializePayload_RawText_ProducesValidJsonString()
    {
        const string rawPayload = "plain text payload";

        var json = DlqJsonSerializer.SerializePayload(rawPayload);

        Assert.NotNull(json);
        using var doc = JsonDocument.Parse(json!);
        Assert.Equal(JsonValueKind.String, doc.RootElement.ValueKind);
        Assert.Equal(rawPayload, doc.RootElement.GetString());
    }
}
