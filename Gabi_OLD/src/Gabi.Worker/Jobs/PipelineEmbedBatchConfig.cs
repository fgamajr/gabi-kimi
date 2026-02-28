using System.Collections.Generic;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Embed batch sizing loaded from sources_v2.yaml defaults.pipeline.embed.
/// </summary>
public sealed record PipelineEmbedBatchConfig(int MaxCharsPerBatch, int MaxDocsPerBatch, int MinDocsPerBatch)
{
    public static readonly PipelineEmbedBatchConfig Default = new(500_000, 32, 1);

    /// <summary>
    /// Loads from GABI_SOURCES_PATH (defaults.pipeline.embed). Returns Default if missing or on error.
    /// </summary>
    public static PipelineEmbedBatchConfig Load()
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
                || !TryGetMap(pipeline, "embed", out var embed))
                return Default;

            var maxChars = GetInt(embed, "max_chars_per_batch", 500_000);
            var maxDocs = GetInt(embed, "max_docs_per_batch", 32);
            var minDocs = GetInt(embed, "min_docs_per_batch", 1);
            return new PipelineEmbedBatchConfig(
                maxChars > 0 ? maxChars : 500_000,
                maxDocs > 0 ? maxDocs : 32,
                minDocs >= 0 ? minDocs : 1);
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
            return i;
        if (obj is long l && l >= int.MinValue && l <= int.MaxValue)
            return (int)l;
        if (int.TryParse(obj.ToString(), out var parsed))
            return parsed;
        return defaultValue;
    }
}
