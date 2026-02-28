using System.Text.Json;
using Gabi.Contracts.Fetch;
using Gabi.Fetch;
using Gabi.Postgres.Entities;
using Microsoft.Extensions.Configuration;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs.Fetch;

internal sealed class JsonApiExtractConfig
{
    public string? TitlePath { get; init; }
    public string? ContentPath { get; init; }
    public string? IdPath { get; init; }
    public string? VidesPath { get; init; }
}

internal sealed record SourceFetchConfig(
    JsonElement? ParseConfig,
    string? ContentStrategy,
    string? FormatType,
    string? Converter,
    JsonApiExtractConfig? JsonApiExtract);

/// <summary>
/// Static helpers for loading and resolving fetch configuration from YAML sources and environment.
/// </summary>
internal static class FetchSourceConfigLoader
{
    public static async Task<SourceFetchConfig> LoadSourceFetchConfigAsync(
        string sourceId,
        IConfiguration configuration,
        CancellationToken ct)
    {
        var sourcesPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
        if (string.IsNullOrEmpty(sourcesPath))
            sourcesPath = configuration["GABI_SOURCES_PATH"];
        if (string.IsNullOrEmpty(sourcesPath))
            sourcesPath = "sources_v2.yaml";

        if (!File.Exists(sourcesPath))
        {
            var cwd = Directory.GetCurrentDirectory();
            sourcesPath = Path.Combine(cwd, sourcesPath);
        }

        if (!File.Exists(sourcesPath))
            return new SourceFetchConfig(null, null, null, null, null);

        try
        {
            var yaml = await File.ReadAllTextAsync(sourcesPath, ct);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(NullNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();

            var doc = deserializer.Deserialize<Dictionary<string, object>>(yaml);

            if (doc == null || !doc.TryGetValue("sources", out var sourcesObj))
                return new SourceFetchConfig(null, null, null, null, null);

            var sources = sourcesObj as Dictionary<object, object>;
            if (sources == null || !sources.TryGetValue(sourceId, out var sourceObj))
                return new SourceFetchConfig(null, null, null, null, null);

            if (sourceObj is not Dictionary<object, object> source)
                return new SourceFetchConfig(null, null, null, null, null);

            JsonElement? parseConfig = null;
            if (source.TryGetValue("parse", out var parseObj))
            {
                var json = JsonSerializer.Serialize(parseObj);
                parseConfig = JsonDocument.Parse(json).RootElement;
            }

            string? contentStrategy = null;
            string? formatType = null;
            string? converter = null;
            JsonApiExtractConfig? jsonApiExtract = null;
            if (source.TryGetValue("fetch", out var fetchObj) && fetchObj is Dictionary<object, object> fetch)
            {
                if (fetch.TryGetValue("content_strategy", out var strategyObj))
                    contentStrategy = strategyObj?.ToString();

                if (fetch.TryGetValue("converter", out var converterObj))
                    converter = converterObj?.ToString();

                if (fetch.TryGetValue("format", out var formatObj) && formatObj is Dictionary<object, object> format &&
                    format.TryGetValue("type", out var typeObj))
                {
                    formatType = typeObj?.ToString();
                }

                if (fetch.TryGetValue("extract", out var extractObj) && extractObj is Dictionary<object, object> extract)
                {
                    jsonApiExtract = new JsonApiExtractConfig
                    {
                        TitlePath = extract.TryGetValue("title_path", out var title) ? title?.ToString() : null,
                        ContentPath = extract.TryGetValue("content_path", out var content) ? content?.ToString() : null,
                        IdPath = extract.TryGetValue("id_path", out var id) ? id?.ToString() : null,
                        VidesPath = extract.TryGetValue("vides_path", out var vides) ? vides?.ToString() : null
                    };
                }
            }

            return new SourceFetchConfig(parseConfig, contentStrategy, formatType, converter, jsonApiExtract);
        }
        catch
        {
            return new SourceFetchConfig(null, null, null, null, null);
        }
    }

    public static CsvFormatConfig GetCsvFormatConfig(SourceRegistryEntity source)
    {
        return new CsvFormatConfig
        {
            Delimiter = "|",
            QuoteChar = "\"",
            Encoding = "utf-8"
        };
    }

    public static int ResolveMaxFieldLength(JsonElement? parseConfig, string? envValue)
    {
        if (parseConfig.HasValue &&
            parseConfig.Value.ValueKind == JsonValueKind.Object &&
            parseConfig.Value.TryGetProperty("limits", out var limits) &&
            limits.ValueKind == JsonValueKind.Object &&
            limits.TryGetProperty("max_field_chars", out var maxFieldChars))
        {
            if (maxFieldChars.ValueKind == JsonValueKind.Number && maxFieldChars.TryGetInt32(out var fromConfig) && fromConfig > 0)
                return fromConfig;
            if (maxFieldChars.ValueKind == JsonValueKind.String && int.TryParse(maxFieldChars.GetString(), out fromConfig) && fromConfig > 0)
                return fromConfig;
        }

        if (int.TryParse(envValue, out var fromEnv) && fromEnv > 0)
            return fromEnv;

        return FetchJobExecutor.DefaultMaxFieldLength;
    }

    public static int ResolveTelemetryEveryRows(string? envValue)
    {
        if (int.TryParse(envValue, out var fromEnv) && fromEnv > 0)
            return fromEnv;
        return 1000;
    }

    public static int ResolveLinkOnlyMaxBytes(string? envValue)
    {
        if (int.TryParse(envValue, out var parsed) && parsed > 0)
            return parsed;
        return 20 * 1024 * 1024;
    }

    public static string ResolveEffectiveFormat(string? formatType, string? contentType, string url)
    {
        var normalized = (formatType ?? string.Empty).Trim().ToLowerInvariant();
        if (!string.IsNullOrEmpty(normalized))
            return normalized;

        var ct = (contentType ?? string.Empty).ToLowerInvariant();
        if (ct.Contains("pdf"))
            return "pdf";
        if (ct.Contains("html"))
            return "html";
        if (ct.Contains("json"))
            return "json";
        if (ct.Contains("text/plain"))
            return "text";

        if (url.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
            return "pdf";
        if (url.EndsWith(".html", StringComparison.OrdinalIgnoreCase) || url.EndsWith(".htm", StringComparison.OrdinalIgnoreCase))
            return "html";
        if (url.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
            return "json";
        if (url.EndsWith(".txt", StringComparison.OrdinalIgnoreCase))
            return "text";

        return "binary";
    }

    public static string ResolveConverterStrategy(string? configuredConverter, string effectiveFormat)
    {
        var configured = (configuredConverter ?? string.Empty).Trim().ToLowerInvariant();
        if (!string.IsNullOrEmpty(configured))
            return configured;

        return effectiveFormat switch
        {
            "html" => "html_to_text",
            "json" => "json_to_text",
            "pdf" => "pdf_to_text_heuristic",
            "text" => "plain_text",
            _ => "unsupported"
        };
    }
}
