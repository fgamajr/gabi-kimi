using System.Text.Json;

namespace Gabi.Worker.Jobs;

public sealed record DlqJobContext(string? SourceId, Guid? OriginalJobId, string? Payload);

public static class DlqJobContextExtractor
{
    public static DlqJobContext Extract(IReadOnlyList<object?>? args)
    {
        if (args == null || args.Count == 0)
        {
            return new DlqJobContext(null, null, null);
        }

        string? sourceId = null;
        Guid? originalJobId = null;
        string? payload = null;

        // Legacy shape: first argument is a JSON object payload that may carry SourceId/JobId.
        if (args[0] is JsonElement legacyElement && legacyElement.ValueKind == JsonValueKind.Object)
        {
            payload = DlqJsonSerializer.SerializePayload(legacyElement);

            if (legacyElement.TryGetProperty("SourceId", out var sourceIdProp))
            {
                sourceId = sourceIdProp.GetString();
            }

            if (legacyElement.TryGetProperty("JobId", out var jobIdProp) && jobIdProp.ValueKind == JsonValueKind.String)
            {
                originalJobId = Guid.TryParse(jobIdProp.GetString(), out var guid) ? guid : null;
            }
        }

        // Current Hangfire runner shape: RunAsync(jobId, jobType, sourceId, payloadJson, ct)
        if (args.Count >= 4)
        {
            originalJobId ??= ParseGuid(args[0]);
            sourceId ??= ParseString(args[2]);
            payload ??= DlqJsonSerializer.SerializePayload(args[3]);
        }

        payload ??= DlqJsonSerializer.SerializePayload(args[0]);

        return new DlqJobContext(sourceId, originalJobId, payload);
    }

    private static string? ParseString(object? value)
    {
        return value switch
        {
            null => null,
            string text => text,
            JsonElement element when element.ValueKind == JsonValueKind.String => element.GetString(),
            _ => value.ToString()
        };
    }

    private static Guid? ParseGuid(object? value)
    {
        return value switch
        {
            Guid guid => guid,
            string text when Guid.TryParse(text, out var parsed) => parsed,
            JsonElement element when element.ValueKind == JsonValueKind.String
                && Guid.TryParse(element.GetString(), out var parsed) => parsed,
            _ => null
        };
    }
}
