using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Jobs;
using Gabi.Fetch;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Fetch executor: downloads CSV files via HTTP streaming, parses row-by-row,
/// applies field mapping, and creates documents.
/// Memory-safe: never loads entire file in memory (300MB budget).
/// </summary>
public class FetchJobExecutor : IJobExecutor
{
    public string JobType => "fetch";

    private readonly GabiDbContext _context;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly ILogger<FetchJobExecutor> _logger;
    private readonly HttpClient _httpClient;
    private const int BatchSize = 25;
    public const int DefaultMaxFieldLength = 262_144;
    private const int DefaultTelemetryEveryRows = 1000;

    public FetchJobExecutor(
        GabiDbContext context,
        IFetchItemRepository fetchItemRepository,
        ILogger<FetchJobExecutor> logger)
    {
        _context = context;
        _fetchItemRepository = fetchItemRepository;
        _logger = logger;

        var handler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(10),
            PooledConnectionIdleTimeout = TimeSpan.FromMinutes(2),
            AutomaticDecompression = DecompressionMethods.All
        };

        _httpClient = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromMinutes(30)
        };
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var startedAt = DateTime.UtcNow;
        var maxDocsPerSource = ReadMaxDocsPerSource(job.Payload);

        var fetchRun = new FetchRunEntity
        {
            JobId = job.Id,
            SourceId = sourceId,
            StartedAt = startedAt,
            Status = "processing"
        };
        _context.FetchRuns.Add(fetchRun);
        await _context.SaveChangesAsync(ct);

        var source = await _context.SourceRegistries.FindAsync([sourceId], ct);
        if (source == null)
        {
            fetchRun.Status = "failed";
            fetchRun.ErrorSummary = $"Source {sourceId} not found";
            fetchRun.CompletedAt = DateTime.UtcNow;
            await _context.SaveChangesAsync(ct);
            return new JobResult { Success = false, ErrorMessage = $"Source {sourceId} not found" };
        }

        var candidates = await _fetchItemRepository.GetBySourceAndStatusesAsync(
            sourceId,
            limit: 5000,
            statuses: ["pending", "failed"],
            ct);

        if (candidates.Count == 0)
        {
            fetchRun.CompletedAt = DateTime.UtcNow;
            fetchRun.Status = "completed";
            fetchRun.ItemsTotal = 0;
            await _context.SaveChangesAsync(ct);
            progress.Report(new JobProgress { PercentComplete = 100, Message = "Nenhum fetch_item pendente" });
            return new JobResult { Success = true };
        }

        if (maxDocsPerSource.HasValue)
        {
            _logger.LogInformation(
                "Fetch cap enabled for {SourceId}: max_docs_per_source={MaxDocs}",
                sourceId,
                maxDocsPerSource.Value);
        }

        var parseConfig = await LoadParseConfigAsync(sourceId, ct);
        var maxFieldLength = ResolveMaxFieldLength(parseConfig, Environment.GetEnvironmentVariable("GABI_FETCH_MAX_FIELD_CHARS"));
        var telemetryEveryRows = ResolveTelemetryEveryRows(Environment.GetEnvironmentVariable("GABI_FETCH_TELEMETRY_EVERY_ROWS"));
        var csvConfig = GetCsvFormatConfig(source);

        var total = candidates.Count;
        var completed = 0;
        var failed = 0;
        var totalDocs = 0;
        var totalRows = 0;
        var capped = false;
        var totalTruncatedFields = 0;

        for (var i = 0; i < candidates.Count; i++)
        {
            if (IsCapReached(totalDocs, maxDocsPerSource))
            {
                capped = true;
                break;
            }

            var item = candidates[i];
            try
            {
                item.Status = "processing";
                item.Attempts++;
                item.StartedAt = DateTime.UtcNow;
                item.FetchRunId = fetchRun.Id;
                await _context.SaveChangesAsync(ct);

                var link = await _context.DiscoveredLinks.FindAsync([item.DiscoveredLinkId], ct);
                int? remainingCap = maxDocsPerSource.HasValue
                    ? Math.Max(0, maxDocsPerSource.Value - totalDocs)
                    : null;

                var result = await FetchAndParseAsync(
                    item.Url,
                    link?.Etag,
                    link?.LastModified?.ToString("R"),
                    csvConfig,
                    parseConfig,
                    remainingCap,
                    maxFieldLength,
                    telemetryEveryRows,
                    sourceId,
                    item,
                    ct);

                if (result.SkippedUnchanged)
                {
                    item.Status = "skipped_unchanged";
                    item.CompletedAt = DateTime.UtcNow;
                    _logger.LogInformation("Fetch skipped (unchanged): {Url}", item.Url);
                }
                else if (result.SkippedFormat)
                {
                    item.Status = "skipped_format";
                    item.CompletedAt = DateTime.UtcNow;
                    item.LastError = "PDF format not yet supported";
                    _logger.LogInformation("Fetch skipped (unsupported format): {Url}", item.Url);
                }
                else
                {
                    item.Status = result.Capped ? "capped" : "completed";
                    item.CompletedAt = DateTime.UtcNow;
                    totalDocs += result.DocumentsCreated;
                    totalRows += result.RowsProcessed;
                    totalTruncatedFields += result.TruncatedFields;
                    capped = capped || result.Capped;
                }

                if (!string.IsNullOrEmpty(result.NewEtag) && link != null)
                {
                    link.Etag = result.NewEtag;
                    if (!string.IsNullOrEmpty(result.NewLastModified) &&
                        DateTimeOffset.TryParse(result.NewLastModified, out var lm))
                    {
                        link.LastModified = lm.UtcDateTime;
                    }
                    link.UpdatedAt = DateTime.UtcNow;
                }

                completed++;
            }
            catch (Exception ex)
            {
                failed++;
                item.Status = "failed";
                item.LastError = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message;
                item.CompletedAt = DateTime.UtcNow;
                _logger.LogError(ex, "Fetch failed for {Url}", item.Url);
            }

            await _context.SaveChangesAsync(ct);

            var percent = (int)Math.Round(((i + 1) * 100.0) / total);
            progress.Report(new JobProgress
            {
                PercentComplete = percent,
                Message = $"Fetch {i + 1}/{total}",
                Metrics = new Dictionary<string, object>
                {
                    ["items_total"] = total,
                    ["items_completed"] = completed,
                    ["items_failed"] = failed,
                    ["documents_created"] = totalDocs,
                    ["rows_processed"] = totalRows,
                    ["fields_truncated"] = totalTruncatedFields,
                    ["capped"] = capped
                }
            });

            if (capped)
            {
                break;
            }
        }

        fetchRun.CompletedAt = DateTime.UtcNow;
        fetchRun.ItemsTotal = total;
        fetchRun.ItemsCompleted = completed;
        fetchRun.ItemsFailed = failed;

        if (capped && maxDocsPerSource.HasValue)
        {
            fetchRun.Status = "capped";
            fetchRun.ErrorSummary = $"Fetch capped at {maxDocsPerSource.Value} documents";
        }
        else
        {
            fetchRun.Status = failed == 0 ? "completed" : (completed > 0 ? "partial" : "failed");
            fetchRun.ErrorSummary = failed == 0 ? null : $"{failed} item(ns) falharam";
        }

        await _context.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Fetch finished for {SourceId}: items={Total}, completed={Completed}, failed={Failed}, docs={Docs}, truncated={Truncated}, capped={Capped}",
            sourceId, total, completed, failed, totalDocs, totalTruncatedFields, capped);

        return new JobResult
        {
            Success = failed < total,
            Metadata = new Dictionary<string, object>
            {
                ["fetch_run_id"] = fetchRun.Id.ToString(),
                ["items_total"] = total,
                ["items_completed"] = completed,
                ["items_failed"] = failed,
                ["documents_created"] = totalDocs,
                ["rows_processed"] = totalRows,
                ["fields_truncated"] = totalTruncatedFields,
                ["capped"] = capped
            }
        };
    }

    private async Task<FetchResult> FetchAndParseAsync(
        string url,
        string? etag,
        string? lastModified,
        CsvFormatConfig csvConfig,
        JsonElement? parseConfig,
        int? maxDocsForItem,
        int maxFieldLength,
        int telemetryEveryRows,
        string sourceId,
        FetchItemEntity item,
        CancellationToken ct)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (!string.IsNullOrEmpty(etag))
            request.Headers.IfNoneMatch.Add(new EntityTagHeaderValue($"\"{etag}\""));
        if (!string.IsNullOrEmpty(lastModified) && DateTimeOffset.TryParse(lastModified, out var lm))
            request.Headers.IfModifiedSince = lm;

        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);

        if (response.StatusCode == HttpStatusCode.NotModified)
            return new FetchResult { SkippedUnchanged = true };

        response.EnsureSuccessStatusCode();

        var newEtag = response.Headers.ETag?.Tag?.Trim('"');
        var newLastModified = response.Content.Headers.LastModified?.ToString("R");
        var contentLength = response.Content.Headers.ContentLength;
        var contentType = response.Content.Headers.ContentType?.MediaType ?? string.Empty;

        if (contentType.Contains("application/pdf", StringComparison.OrdinalIgnoreCase)
            || url.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogWarning("Skipping PDF content for {Url} - PDF parsing not yet implemented", url);
            return new FetchResult
            {
                SkippedFormat = true,
                NewEtag = newEtag,
                NewLastModified = newLastModified
            };
        }

        _logger.LogInformation(
            "Fetching {Url} (Content-Length: {SizeMB:F1}MB)",
            url,
            (contentLength ?? 0) / (1024.0 * 1024.0));

        await using var stream = await response.Content.ReadAsStreamAsync(ct);

        return await ProcessCsvStreamAsync(
            stream,
            csvConfig,
            parseConfig,
            maxDocsForItem,
            maxFieldLength,
            telemetryEveryRows,
            sourceId,
            item,
            newEtag,
            newLastModified,
            ct);
    }

    private async Task<FetchResult> ProcessCsvStreamAsync(
        Stream stream,
        CsvFormatConfig csvConfig,
        JsonElement? parseConfig,
        int? maxDocsForItem,
        int maxFieldLength,
        int telemetryEveryRows,
        string sourceId,
        FetchItemEntity item,
        string? newEtag,
        string? newLastModified,
        CancellationToken ct)
    {
        var documentsCreated = 0;
        var rowsProcessed = 0;
        var capped = false;
        var truncatedFields = 0;
        var parser = new CsvStreamingParser(maxFieldLength: maxFieldLength);
        var batch = new List<DocumentEntity>(BatchSize);

        await foreach (var row in parser.ParseRowsAsync(stream, csvConfig, ct))
        {
            if (IsCapReached(documentsCreated, maxDocsForItem))
            {
                capped = true;
                break;
            }

            rowsProcessed++;
            truncatedFields += row.Warnings.Count(w => w.Contains("truncated", StringComparison.OrdinalIgnoreCase));

            try
            {
                var docId = ExtractDocumentId(row.Fields, parseConfig);
                var externalId = docId ?? $"row-{rowsProcessed}";

                var doc = new DocumentEntity
                {
                    LinkId = item.DiscoveredLinkId,
                    FetchItemId = item.Id,
                    SourceId = sourceId,
                    ExternalId = externalId,
                    DocumentId = docId,
                    Title = ExtractTitle(row.Fields, parseConfig),
                    Content = ExtractContent(row.Fields, parseConfig),
                    ContentHash = ComputeHash(row.Fields),
                    Status = "pending",
                    ProcessingStage = "fetch_completed",
                    Metadata = JsonSerializer.Serialize(row.Fields)
                };

                batch.Add(doc);
                documentsCreated++;

                if (batch.Count >= BatchSize)
                {
                    await InsertBatchAsync(batch, ct);
                    batch.Clear();
                    batch.Capacity = BatchSize;

                    if (documentsCreated % 500 == 0)
                    {
                        GC.Collect(GC.MaxGeneration, GCCollectionMode.Optimized);
                        _logger.LogDebug("GC triggered after {Count} documents", documentsCreated);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to process row {RowNumber}", row.RowNumber);
            }

            if (telemetryEveryRows > 0 && rowsProcessed % telemetryEveryRows == 0)
            {
                var managedBytes = GC.GetTotalMemory(forceFullCollection: false);
                var rssBytes = Process.GetCurrentProcess().WorkingSet64;
                var cgroupBytes = GetContainerMemoryUsageBytes();
                _logger.LogInformation(
                    "Fetch telemetry source={SourceId} item={FetchItemId} rows={Rows} docs={Docs} truncated={Truncated} heap_mb={HeapMB:F1} rss_mb={RssMB:F1} container_mb={ContainerMB:F1}",
                    sourceId,
                    item.Id,
                    rowsProcessed,
                    documentsCreated,
                    truncatedFields,
                    managedBytes / (1024.0 * 1024.0),
                    rssBytes / (1024.0 * 1024.0),
                    cgroupBytes.HasValue ? cgroupBytes.Value / (1024.0 * 1024.0) : -1);
            }
        }

        if (batch.Count > 0)
        {
            await InsertBatchAsync(batch, ct);
        }

        return new FetchResult
        {
            SkippedUnchanged = false,
            RowsProcessed = rowsProcessed,
            DocumentsCreated = documentsCreated,
            TruncatedFields = truncatedFields,
            Capped = capped,
            NewEtag = newEtag,
            NewLastModified = newLastModified
        };
    }

    private async Task InsertBatchAsync(List<DocumentEntity> batch, CancellationToken ct)
    {
        foreach (var doc in batch)
        {
            const string sql = """
                INSERT INTO documents ("Id", "LinkId", "FetchItemId", "SourceId", "ExternalId",
                    "DocumentId", "Title", "Content", "ContentHash", "Status", "ProcessingStage",
                    "Metadata", "CreatedAt", "UpdatedAt", "CreatedBy", "UpdatedBy")
                VALUES (@Id, @LinkId, @FetchItemId, @SourceId, @ExternalId,
                    @DocumentId, @Title, @Content, @ContentHash, @Status, @ProcessingStage,
                    @Metadata::jsonb, @CreatedAt, @UpdatedAt, @CreatedBy, @UpdatedBy)
                """;

            var parameters = new object[]
            {
                new NpgsqlParameter("@Id", doc.Id),
                new NpgsqlParameter("@LinkId", doc.LinkId),
                new NpgsqlParameter("@FetchItemId", doc.FetchItemId ?? (object)DBNull.Value),
                new NpgsqlParameter("@SourceId", doc.SourceId),
                new NpgsqlParameter("@ExternalId", doc.ExternalId ?? (object)DBNull.Value),
                new NpgsqlParameter("@DocumentId", doc.DocumentId ?? (object)DBNull.Value),
                new NpgsqlParameter("@Title", doc.Title ?? (object)DBNull.Value),
                new NpgsqlParameter("@Content", doc.Content ?? (object)DBNull.Value),
                new NpgsqlParameter("@ContentHash", doc.ContentHash ?? (object)DBNull.Value),
                new NpgsqlParameter("@Status", doc.Status),
                new NpgsqlParameter("@ProcessingStage", doc.ProcessingStage ?? (object)DBNull.Value),
                new NpgsqlParameter("@Metadata", doc.Metadata ?? "{}"),
                new NpgsqlParameter("@CreatedAt", doc.CreatedAt),
                new NpgsqlParameter("@UpdatedAt", doc.UpdatedAt),
                new NpgsqlParameter("@CreatedBy", doc.CreatedBy ?? "system"),
                new NpgsqlParameter("@UpdatedBy", doc.UpdatedBy ?? "system")
            };

            await _context.Database.ExecuteSqlRawAsync(sql, parameters, ct);
        }

        _logger.LogDebug("Batch of {Count} documents inserted via raw SQL", batch.Count);
    }

    private async Task<JsonElement?> LoadParseConfigAsync(string sourceId, CancellationToken ct)
    {
        var sourcesPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH") ?? "sources_v2.yaml";

        if (!File.Exists(sourcesPath))
        {
            var cwd = Directory.GetCurrentDirectory();
            sourcesPath = Path.Combine(cwd, sourcesPath);
        }

        if (!File.Exists(sourcesPath))
            return null;

        try
        {
            var yaml = await File.ReadAllTextAsync(sourcesPath, ct);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();

            var doc = deserializer.Deserialize<Dictionary<string, object>>(yaml);

            if (doc == null || !doc.TryGetValue("sources", out var sourcesObj))
                return null;

            var sources = sourcesObj as Dictionary<object, object>;
            if (sources == null || !sources.TryGetValue(sourceId, out var sourceObj))
                return null;

            var source = sourceObj as Dictionary<object, object>;
            if (source == null || !source.TryGetValue("parse", out var parseObj))
                return null;

            var json = JsonSerializer.Serialize(parseObj);
            return JsonDocument.Parse(json).RootElement;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to load parse config for {SourceId}", sourceId);
            return null;
        }
    }

    private static CsvFormatConfig GetCsvFormatConfig(SourceRegistryEntity source)
    {
        return new CsvFormatConfig
        {
            Delimiter = "|",
            QuoteChar = "\"",
            Encoding = "utf-8"
        };
    }

    private static string? ExtractDocumentId(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig) &&
                fieldsConfig.TryGetProperty("document_id", out var docIdConfig))
            {
                var source = docIdConfig.GetProperty("source").GetString();
                if (source != null && fields.TryGetValue(source, out var value))
                {
                    var transforms = GetTransforms(docIdConfig);
                    return Transforms.ApplyChain(value, transforms);
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    private static string? ExtractTitle(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig))
            {
                foreach (var prop in fieldsConfig.EnumerateObject())
                {
                    if (prop.Name == "title" || prop.Name == "year")
                    {
                        var source = prop.Value.GetProperty("source").GetString();
                        if (source != null && fields.TryGetValue(source, out var value))
                        {
                            var transforms = GetTransforms(prop.Value);
                            return Transforms.ApplyChain(value, transforms);
                        }
                    }
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    private static string? ExtractContent(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig) &&
                fieldsConfig.TryGetProperty("content", out var contentConfig))
            {
                var source = contentConfig.GetProperty("source").GetString();
                if (source != null && fields.TryGetValue(source, out var value))
                {
                    var transforms = GetTransforms(contentConfig);
                    return Transforms.ApplyChain(value, transforms);
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    private static List<string> GetTransforms(JsonElement fieldConfig)
    {
        var transforms = new List<string>();
        if (fieldConfig.TryGetProperty("transforms", out var transformsProp) &&
            transformsProp.ValueKind == JsonValueKind.Array)
        {
            foreach (var t in transformsProp.EnumerateArray())
            {
                var transform = t.GetString();
                if (transform != null)
                    transforms.Add(transform);
            }
        }
        return transforms;
    }

    private static string ComputeHash(Dictionary<string, string> fields)
    {
        var content = string.Join("|", fields.Values);
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static int? ReadMaxDocsPerSource(Dictionary<string, object>? payload)
    {
        if (payload == null || !payload.TryGetValue("max_docs_per_source", out var raw) || raw == null)
            return null;

        static int? Normalize(int value) => value > 0 ? value : null;
        static int? ParseString(string? text)
        {
            if (string.IsNullOrWhiteSpace(text))
                return null;
            if (int.TryParse(text, out var parsed))
                return Normalize(parsed);
            if (long.TryParse(text, out var parsedLong) && parsedLong is > 0 and <= int.MaxValue)
                return (int)parsedLong;
            if (double.TryParse(text, out var parsedDouble) && parsedDouble > 0)
                return Normalize((int)Math.Floor(parsedDouble));
            return null;
        }

        return raw switch
        {
            int v => Normalize(v),
            long v when v > 0 && v <= int.MaxValue => (int)v,
            double v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            float v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            decimal v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            string s => ParseString(s),
            JsonElement element => element.ValueKind switch
            {
                JsonValueKind.Number when element.TryGetInt32(out var parsedInt) => Normalize(parsedInt),
                JsonValueKind.Number when element.TryGetInt64(out var parsedLong) && parsedLong is > 0 and <= int.MaxValue => (int)parsedLong,
                JsonValueKind.String => ParseString(element.GetString()),
                _ => ParseString(element.ToString())
            },
            _ => ParseString(raw.ToString())
        };
    }

    public static bool IsCapReached(int documentsCreated, int? maxDocsPerSource)
    {
        return maxDocsPerSource.HasValue && documentsCreated >= maxDocsPerSource.Value;
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

        return DefaultMaxFieldLength;
    }

    private static int ResolveTelemetryEveryRows(string? envValue)
    {
        if (int.TryParse(envValue, out var fromEnv) && fromEnv > 0)
            return fromEnv;
        return DefaultTelemetryEveryRows;
    }

    private static long? GetContainerMemoryUsageBytes()
    {
        try
        {
            const string cgroupV2Path = "/sys/fs/cgroup/memory.current";
            if (File.Exists(cgroupV2Path))
            {
                var text = File.ReadAllText(cgroupV2Path).Trim();
                if (long.TryParse(text, out var value) && value >= 0)
                    return value;
            }

            const string cgroupV1Path = "/sys/fs/cgroup/memory/memory.usage_in_bytes";
            if (File.Exists(cgroupV1Path))
            {
                var text = File.ReadAllText(cgroupV1Path).Trim();
                if (long.TryParse(text, out var value) && value >= 0)
                    return value;
            }
        }
        catch
        {
            // best-effort telemetry only
        }

        return null;
    }

    private record FetchResult
    {
        public bool SkippedUnchanged { get; init; }
        public bool SkippedFormat { get; init; }
        public int RowsProcessed { get; init; }
        public int DocumentsCreated { get; init; }
        public int TruncatedFields { get; init; }
        public bool Capped { get; init; }
        public string? NewEtag { get; init; }
        public string? NewLastModified { get; init; }
    }
}
