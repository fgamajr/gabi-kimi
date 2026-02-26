using System.Collections.Generic;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Backpressure and embed batch thresholds loaded from sources_v2.yaml defaults.pipeline.
/// </summary>
public sealed record PipelineBackpressureConfig(
    int MaxPendingFetch,
    int MaxPendingIngest,
    int MaxPendingEmbed)
{
    public static readonly PipelineBackpressureConfig Default = new(10_000, 5_000, 500);

    /// <summary>
    /// Loads from GABI_SOURCES_PATH (defaults.pipeline.backpressure). Returns Default if missing or on error.
    /// </summary>
    public static PipelineBackpressureConfig Load()
    {
        var path = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH") ?? "sources_v2.yaml";
        if (!File.Exists(path))
            path = Path.Combine(Directory.GetCurrentDirectory(), path);
        if (!File.Exists(path))
            return Default;

        try
        {
            var yaml = File.ReadAllText(path);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();
            var root = deserializer.Deserialize<Dictionary<object, object>>(yaml);
            if (root == null)
                return Default;

            if (!TryGetMap(root, "defaults", out var defaults)
                || !TryGetMap(defaults, "pipeline", out var pipeline)
                || !TryGetMap(pipeline, "backpressure", out var bp))
                return Default;

            var maxFetch = GetInt(bp, "max_pending_fetch", 10_000);
            var maxIngest = GetInt(bp, "max_pending_ingest", 5_000);
            var maxEmbed = GetInt(bp, "max_pending_embed", 500);
            return new PipelineBackpressureConfig(maxFetch, maxIngest, maxEmbed);
        }
        catch
        {
            return Default;
        }
    }

    private static bool TryGetMap(IReadOnlyDictionary<object, object> map, string key, out Dictionary<object, object> value)
    {
        if (map.TryGetValue(key, out var obj) && obj is Dictionary<object, object> typed)
        {
            value = typed;
            return true;
        }
        value = new Dictionary<object, object>();
        return false;
    }

    private static int GetInt(Dictionary<object, object> map, string key, int defaultValue)
    {
        if (!map.TryGetValue(key, out var obj) || obj == null)
            return defaultValue;
        if (obj is int i)
            return i > 0 ? i : defaultValue;
        if (obj is long l && l > 0 && l <= int.MaxValue)
            return (int)l;
        if (int.TryParse(obj.ToString(), out var parsed) && parsed > 0)
            return parsed;
        return defaultValue;
    }
}
