using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Text.Json;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
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
    private const int FetchCandidatePageSize = 100;
    private const int ClaimBatchRetryAttempts = 5;
    public const int DefaultMaxFieldLength = 262_144;
    private const int DefaultTelemetryEveryRows = 1000;
    private const int DefaultLinkOnlyMaxBytes = 20 * 1024 * 1024;
    private const int DefaultMaxConvertedTextChars = 100_000;
    private static readonly Regex HtmlScriptStyleRegex = new(@"<(script|style)\b[^>]*>.*?</\1>", RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex HtmlTitleRegex = new(@"<title\b[^>]*>(?<title>.*?)</title>", RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex PdfLiteralTextRegex = new(@"\((?<text>(?:\\.|[^\\)])+)\)\s*Tj", RegexOptions.Compiled);
    private static readonly Regex PdfArrayTextRegex = new(@"\[(?<body>.*?)\]\s*TJ", RegexOptions.Compiled | RegexOptions.Singleline);
    private static readonly Regex PdfArrayLiteralRegex = new(@"\((?<text>(?:\\.|[^\\)])+)\)", RegexOptions.Compiled);
    private static readonly Regex PrintableSequenceRegex = new(@"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9\s,.;:()/%\-]{30,}", RegexOptions.Compiled);

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
        var stageStopwatch = Stopwatch.StartNew();
        using var activity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.fetch", ActivityKind.Internal);
        activity?.SetTag("source.id", sourceId);
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
            activity?.SetStatus(ActivityStatusCode.Error, $"Source {sourceId} not found");
            activity?.SetTag("error.type", "source_not_found");
            PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "fetch");
            return new JobResult { Success = false, ErrorMessage = $"Source {sourceId} not found" };
        }

        // Cleanup: reset items stuck in "processing" from previous interrupted runs
        // This prevents stalls when jobs are cancelled mid-processing
        var stuckItemsReset = await ResetStuckProcessingItemsAsync(sourceId, ct);
        if (stuckItemsReset > 0)
        {
            _logger.LogWarning(
                "Reset {Count} stuck processing items for source {SourceId}",
                stuckItemsReset,
                sourceId);
        }

        var candidateStatuses = new[] { "pending", "failed" };
        var total = await _fetchItemRepository.CountBySourceAndStatusesAsync(sourceId, candidateStatuses, ct);
        if (total == 0)
        {
            fetchRun.CompletedAt = DateTime.UtcNow;
            fetchRun.Status = "completed";
            fetchRun.ItemsTotal = 0;
            await _context.SaveChangesAsync(ct);
            progress.Report(new JobProgress { PercentComplete = 100, Message = "Nenhum fetch_item pendente" });
            activity?.SetTag("docs.count", 0);
            PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "fetch");
            return new JobResult { Success = true };
        }

        if (maxDocsPerSource.HasValue)
        {
            _logger.LogInformation(
                "Fetch cap enabled for {SourceId}: max_docs_per_source={MaxDocs}",
                sourceId,
                maxDocsPerSource.Value);
        }

        var sourceFetchConfig = await LoadSourceFetchConfigAsync(sourceId, ct);
        var parseConfig = sourceFetchConfig.ParseConfig;
        var fetchContentStrategy = sourceFetchConfig.ContentStrategy;
        var jsonApiExtractConfig = sourceFetchConfig.JsonApiExtract;
        var fetchFormatType = sourceFetchConfig.FormatType;
        var fetchConverter = sourceFetchConfig.Converter;
        var maxFieldLength = ResolveMaxFieldLength(parseConfig, Environment.GetEnvironmentVariable("GABI_FETCH_MAX_FIELD_CHARS"));
        var telemetryEveryRows = ResolveTelemetryEveryRows(Environment.GetEnvironmentVariable("GABI_FETCH_TELEMETRY_EVERY_ROWS"));
        var linkOnlyMaxBytes = ResolveLinkOnlyMaxBytes(Environment.GetEnvironmentVariable("GABI_FETCH_LINK_ONLY_MAX_BYTES"));
        var csvConfig = GetCsvFormatConfig(source);

        var completed = 0;
        var failed = 0;
        var totalDocs = 0;
        var totalRows = 0;
        var capped = false;
        var totalTruncatedFields = 0;

        if (string.Equals(fetchContentStrategy, "link_only", StringComparison.OrdinalIgnoreCase))
        {
            var processed = 0;
            while (true)
            {
                if (IsCapReached(totalDocs, maxDocsPerSource))
                {
                    capped = true;
                    break;
                }

                var pageItems = await ClaimNextBatchWithRetryAsync(
                    sourceId,
                    FetchCandidatePageSize,
                    candidateStatuses,
                    fetchRun.Id,
                    "fetch_link_only",
                    ct);
                if (pageItems.Count == 0)
                    break;

                var stopAfterCurrentBatch = false;
                foreach (var item in pageItems)
                {
                    if (IsCapReached(totalDocs, maxDocsPerSource))
                    {
                        capped = true;
                        stopAfterCurrentBatch = true;
                        MarkDeferredByCap(item);
                        continue;
                    }

                    try
                    {
                        if (TryGetUnsupportedUrlScheme(item.Url, out var unsupportedScheme))
                        {
                            item.Status = "skipped_format";
                            item.LastError = $"unsupported_url_scheme={unsupportedScheme}";
                            item.CompletedAt = DateTime.UtcNow;
                            completed++;
                            processed++;
                        }
                        else
                        {
                            var link = await _context.DiscoveredLinks.FindAsync([item.DiscoveredLinkId], ct);
                            var result = await FetchAndConvertLinkOnlyAsync(
                                item.Url,
                                link?.Etag,
                                link?.LastModified?.ToString("R"),
                                link?.Metadata,
                                sourceId,
                                item,
                                fetchFormatType,
                                fetchConverter,
                                linkOnlyMaxBytes,
                                ct);

                            if (result.SkippedUnchanged)
                            {
                                item.Status = "skipped_unchanged";
                                item.LastError = null;
                            }
                            else if (result.SkippedFormat)
                            {
                                item.Status = "skipped_format";
                                item.LastError = result.ErrorDetail ?? "unsupported_format";
                            }
                            else
                            {
                                item.Status = result.Capped ? "capped" : "completed";
                                item.LastError = null;
                                totalDocs += result.DocumentsCreated;
                                totalRows += result.RowsProcessed;
                            }

                            item.CompletedAt = DateTime.UtcNow;
                            completed++;
                            processed++;
                            capped = capped || result.Capped;

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
                        }
                    }
                    catch (Exception ex)
                    {
                        failed++;
                        processed++;
                        item.Status = "failed";
                        item.LastError = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message;
                        item.CompletedAt = DateTime.UtcNow;
                        _logger.LogError(ex, "Fetch link_only conversion failed for {Url}", item.Url);
                    }

                    var percent = (int)Math.Round((processed * 100.0) / Math.Max(total, processed));
                    progress.Report(new JobProgress
                    {
                        PercentComplete = percent,
                        Message = $"Fetch link_only {processed}/{total}",
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
                }

                await SaveChangesWithRetryAsync(ct);
                _context.ChangeTracker.Clear();
                if (stopAfterCurrentBatch)
                    break;
            }

            if (maxDocsPerSource.HasValue && (capped || processed >= maxDocsPerSource.Value))
            {
                var released = await ReleaseCappedProcessingItemsAsync(sourceId, fetchRun.Id, ct);
                if (released > 0)
                {
                    _logger.LogInformation(
                        "Released {Count} fetch_items from processing to pending after cap for {SourceId} (link_only mode)",
                        released,
                        sourceId);
                }
            }

            var fetchRunLinkOnly = await _context.FetchRuns.FindAsync([fetchRun.Id], ct)
                ?? throw new InvalidOperationException($"FetchRun {fetchRun.Id} not found for link_only finalization.");
            fetchRunLinkOnly.CompletedAt = DateTime.UtcNow;
            fetchRunLinkOnly.ItemsTotal = total;
            fetchRunLinkOnly.ItemsCompleted = completed;
            fetchRunLinkOnly.ItemsFailed = failed;
            if (capped && maxDocsPerSource.HasValue)
            {
                fetchRunLinkOnly.Status = "capped";
                fetchRunLinkOnly.ErrorSummary = $"content_strategy=link_only; limited_to={maxDocsPerSource.Value}";
            }
            else
            {
                fetchRunLinkOnly.Status = failed == 0 ? "completed" : (completed > 0 ? "partial" : "failed");
                fetchRunLinkOnly.ErrorSummary = failed == 0 ? "content_strategy=link_only" : $"{failed} item(ns) falharam";
            }
            await _context.SaveChangesAsync(ct);

            _logger.LogInformation(
                "Fetch finished in link_only mode for {SourceId}: items={Total}, completed={Completed}, failed={Failed}, docs={Docs}",
                sourceId,
                total,
                completed,
                failed,
                totalDocs);
            activity?.SetTag("docs.count", totalDocs);
            activity?.SetTag("fetch.items.count", completed);
            PipelineTelemetry.RecordDocsProcessed(totalDocs, sourceId, "fetch");
            PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "fetch");

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
                    ["fields_truncated"] = 0,
                    ["capped"] = capped,
                    ["content_strategy"] = "link_only"
                }
            };
        }

        var processedCount = 0;
        while (true)
        {
            if (capped || IsCapReached(totalDocs, maxDocsPerSource))
            {
                capped = true;
                break;
            }

            var pageItems = await ClaimNextBatchWithRetryAsync(
                sourceId,
                FetchCandidatePageSize,
                candidateStatuses,
                fetchRun.Id,
                "fetch",
                ct);
            if (pageItems.Count == 0)
                break;

            var stopAfterCurrentBatch = false;
            foreach (var item in pageItems)
            {
                if (IsCapReached(totalDocs, maxDocsPerSource))
                {
                    capped = true;
                    stopAfterCurrentBatch = true;
                    MarkDeferredByCap(item);
                    await SaveChangesWithRetryAsync(ct);
                    continue;
                }

                try
                {
                    if (TryGetUnsupportedUrlScheme(item.Url, out var unsupportedScheme))
                    {
                        item.Status = "skipped_format";
                        item.LastError = $"unsupported_url_scheme={unsupportedScheme}";
                        item.CompletedAt = DateTime.UtcNow;
                        _logger.LogInformation(
                            "Fetch skipped (unsupported URL scheme: {Scheme}) for {Url}",
                            unsupportedScheme,
                            item.Url);
                        completed++;
                    }
                    else
                    {
                        var link = await _context.DiscoveredLinks.FindAsync([item.DiscoveredLinkId], ct);
                        int? remainingCap = maxDocsPerSource.HasValue
                            ? Math.Max(0, maxDocsPerSource.Value - totalDocs)
                            : null;

                        FetchResult result;
                        if (string.Equals(fetchContentStrategy, "json_api", StringComparison.OrdinalIgnoreCase))
                        {
                            result = await FetchAndParseJsonApiAsync(
                                item.Url,
                                link?.Etag,
                                link?.LastModified?.ToString("R"),
                                link?.Metadata,
                                jsonApiExtractConfig,
                                sourceId,
                                item,
                                ct);
                        }
                        else
                        {
                            result = await FetchAndParseAsync(
                                item.Url,
                                link?.Etag,
                                link?.LastModified?.ToString("R"),
                                link?.Metadata,
                                csvConfig,
                                parseConfig,
                                remainingCap,
                                maxFieldLength,
                                telemetryEveryRows,
                                sourceId,
                                item,
                                ct);
                        }

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
                }
                catch (Exception ex)
                {
                    failed++;
                    item.Status = "failed";
                    item.LastError = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message;
                    item.CompletedAt = DateTime.UtcNow;
                    activity?.SetTag("error.type", ex.GetType().Name);
                    _logger.LogError(ex, "Fetch failed for {Url}", item.Url);
                }

                processedCount++;
                await SaveChangesWithRetryAsync(ct);

                var percent = (int)Math.Round((processedCount * 100.0) / Math.Max(total, processedCount));
                progress.Report(new JobProgress
                {
                    PercentComplete = percent,
                    Message = $"Fetch {processedCount}/{total}",
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
            }

            _context.ChangeTracker.Clear();
            if (stopAfterCurrentBatch)
                break;
        }

        if (maxDocsPerSource.HasValue && (capped || totalDocs >= maxDocsPerSource.Value))
        {
            var released = await ReleaseCappedProcessingItemsAsync(sourceId, fetchRun.Id, ct);
            if (released > 0)
            {
                _logger.LogInformation(
                    "Released {Count} fetch_items from processing to pending after cap for {SourceId}",
                    released,
                    sourceId);
            }
        }

        var fetchRunFinal = await _context.FetchRuns.FindAsync([fetchRun.Id], ct)
            ?? throw new InvalidOperationException($"FetchRun {fetchRun.Id} not found for finalization.");
        fetchRunFinal.CompletedAt = DateTime.UtcNow;
        fetchRunFinal.ItemsTotal = total;
        fetchRunFinal.ItemsCompleted = completed;
        fetchRunFinal.ItemsFailed = failed;

        if (capped && maxDocsPerSource.HasValue)
        {
            fetchRunFinal.Status = "capped";
            fetchRunFinal.ErrorSummary = $"Fetch capped at {maxDocsPerSource.Value} documents";
        }
        else
        {
            fetchRunFinal.Status = failed == 0 ? "completed" : (completed > 0 ? "partial" : "failed");
            fetchRunFinal.ErrorSummary = failed == 0 ? null : $"{failed} item(ns) falharam";
        }

        await _context.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Fetch finished for {SourceId}: items={Total}, completed={Completed}, failed={Failed}, docs={Docs}, truncated={Truncated}, capped={Capped}",
            sourceId, total, completed, failed, totalDocs, totalTruncatedFields, capped);
        activity?.SetTag("docs.count", totalDocs);
        activity?.SetTag("fetch.items.count", completed);
        PipelineTelemetry.RecordDocsProcessed(totalDocs, sourceId, "fetch");
        PipelineTelemetry.RecordStageLatency(stageStopwatch.Elapsed.TotalMilliseconds, sourceId, "fetch");

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

    private async Task<FetchResult> FetchAndConvertLinkOnlyAsync(
        string url,
        string? etag,
        string? lastModified,
        string? linkMetadataJson,
        string sourceId,
        FetchItemEntity item,
        string? formatType,
        string? converter,
        int maxBytes,
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
        var contentType = response.Content.Headers.ContentType?.MediaType;
        var contentLength = response.Content.Headers.ContentLength;
        if (contentLength.HasValue && contentLength.Value > maxBytes)
        {
            return new FetchResult
            {
                SkippedFormat = true,
                ErrorDetail = $"link_only_content_too_large={contentLength.Value}",
                NewEtag = newEtag,
                NewLastModified = newLastModified
            };
        }

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        var bytes = await ReadAllBytesWithLimitAsync(stream, maxBytes, ct);
        if (bytes == null)
        {
            return new FetchResult
            {
                SkippedFormat = true,
                ErrorDetail = $"link_only_content_too_large>{maxBytes}",
                NewEtag = newEtag,
                NewLastModified = newLastModified
            };
        }

        var effectiveFormat = ResolveEffectiveFormat(formatType, contentType, url);
        var strategy = ResolveConverterStrategy(converter, effectiveFormat);
        var conversion = ConvertLinkOnlyPayload(bytes, strategy, contentType, url);

        if (!conversion.Success)
        {
            return new FetchResult
            {
                SkippedFormat = true,
                ErrorDetail = conversion.ErrorDetail ?? "link_only_conversion_unsupported",
                NewEtag = newEtag,
                NewLastModified = newLastModified
            };
        }

        var metadataAsObjects = new Dictionary<string, object>(conversion.Metadata, StringComparer.OrdinalIgnoreCase)
        {
            ["converter_strategy"] = strategy,
            ["fetch_format_type"] = effectiveFormat,
            ["fetch_content_type"] = contentType ?? string.Empty,
            ["fetch_url"] = url
        };

        var docId = FirstNonEmpty(
            TryReadMetadataValueAsString(linkMetadataJson, "document_id"),
            TryReadMetadataValueAsString(linkMetadataJson, "id"),
            TryReadMetadataValueAsString(linkMetadataJson, "key"));

        var externalId = FirstNonEmpty(
            TryReadMetadataValueAsString(linkMetadataJson, "external_id"),
            docId,
            ComputeHash(new Dictionary<string, string>
            {
                ["url"] = url,
                ["title"] = conversion.Title ?? string.Empty
            }));

        var title = FirstNonEmpty(
            conversion.Title,
            TryReadMetadataValueAsString(linkMetadataJson, "title"),
            TryReadMetadataValueAsString(linkMetadataJson, "titulo"),
            TryReadMetadataValueAsString(linkMetadataJson, "nome"));

        var content = conversion.Content ?? string.Empty;
        var docEntity = new DocumentEntity
        {
            LinkId = item.DiscoveredLinkId,
            FetchItemId = item.Id,
            SourceId = sourceId,
            ExternalId = externalId!,
            DocumentId = docId,
            Title = title,
            Content = content,
            ContentHash = ComputeHash(new Dictionary<string, string>
            {
                ["external_id"] = externalId!,
                ["content"] = content
            }),
            Status = "pending",
            ProcessingStage = "fetch_completed",
            Metadata = BuildDocumentMetadataJson(linkMetadataJson, metadataAsObjects)
        };

        await InsertBatchAsync([docEntity], ct);
        return new FetchResult
        {
            DocumentsCreated = 1,
            RowsProcessed = 1,
            NewEtag = newEtag,
            NewLastModified = newLastModified
        };
    }

    private async Task<FetchResult> FetchAndParseAsync(
        string url,
        string? etag,
        string? lastModified,
        string? linkMetadataJson,
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
                ErrorDetail = "pdf_without_converter",
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
            linkMetadataJson,
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
        string? linkMetadataJson,
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
                    Metadata = BuildDocumentMetadataJson(linkMetadataJson, row.Fields)
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

    private async Task<FetchResult> FetchAndParseJsonApiAsync(
        string url,
        string? etag,
        string? lastModified,
        string? linkMetadataJson,
        JsonApiExtractConfig? extractConfig,
        string sourceId,
        FetchItemEntity item,
        CancellationToken ct)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
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

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);

        var titlePath = extractConfig?.TitlePath ?? "DetalheDocumento.documentos.documento[0].normaNome";
        var contentPath = extractConfig?.ContentPath ?? "DetalheDocumento.documentos.documento[0].ementa";
        var idPath = extractConfig?.IdPath ?? "DetalheDocumento.documentos.documento[0].norma";
        var videsPath = extractConfig?.VidesPath ?? "DetalheDocumento.documentos.documento[0].vides";

        var extractedTitle = TryReadPathAsString(doc.RootElement, titlePath);
        var extractedContent = TryReadPathAsString(doc.RootElement, contentPath);
        var extractedId = TryReadPathAsString(doc.RootElement, idPath);
        var videsElement = TryReadPath(doc.RootElement, videsPath);
        var normativeForce = DeriveNormativeForce(CollectComentarios(videsElement));

        var extractedMetadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
        {
            ["normative_force"] = normativeForce
        };

        if (!string.IsNullOrWhiteSpace(extractedId))
            extractedMetadata["senado_norma"] = extractedId!;
        if (!string.IsNullOrWhiteSpace(extractedTitle))
            extractedMetadata["senado_norma_nome"] = extractedTitle!;
        if (!string.IsNullOrWhiteSpace(extractedContent))
            extractedMetadata["senado_ementa"] = extractedContent!;

        var externalId = !string.IsNullOrWhiteSpace(extractedId)
            ? extractedId!
            : ComputeHash(new Dictionary<string, string> { ["url"] = url, ["title"] = extractedTitle ?? string.Empty });

        var content = extractedContent ?? extractedTitle ?? string.Empty;
        var docEntity = new DocumentEntity
        {
            LinkId = item.DiscoveredLinkId,
            FetchItemId = item.Id,
            SourceId = sourceId,
            ExternalId = externalId,
            DocumentId = extractedId,
            Title = extractedTitle,
            Content = content,
            ContentHash = ComputeHash(new Dictionary<string, string>
            {
                ["external_id"] = externalId,
                ["content"] = content
            }),
            Status = "pending",
            ProcessingStage = "fetch_completed",
            Metadata = BuildDocumentMetadataJson(linkMetadataJson, extractedMetadata)
        };

        await InsertBatchAsync([docEntity], ct);

        return new FetchResult
        {
            DocumentsCreated = 1,
            RowsProcessed = 1,
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
                ON CONFLICT ("SourceId", "ExternalId") WHERE "RemovedFromSourceAt" IS NULL
                DO UPDATE SET
                    "LinkId" = EXCLUDED."LinkId",
                    "FetchItemId" = EXCLUDED."FetchItemId",
                    "DocumentId" = EXCLUDED."DocumentId",
                    "Title" = EXCLUDED."Title",
                    "Content" = EXCLUDED."Content",
                    "ContentHash" = EXCLUDED."ContentHash",
                    "Status" = EXCLUDED."Status",
                    "ProcessingStage" = EXCLUDED."ProcessingStage",
                    "Metadata" = EXCLUDED."Metadata",
                    "UpdatedAt" = EXCLUDED."UpdatedAt",
                    "UpdatedBy" = EXCLUDED."UpdatedBy"
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

        _logger.LogDebug("Batch of {Count} documents upserted via raw SQL", batch.Count);
    }

    private async Task<SourceFetchConfig> LoadSourceFetchConfigAsync(string sourceId, CancellationToken ct)
    {
        var sourcesPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH") ?? "sources_v2.yaml";

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
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
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
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to load source fetch config for {SourceId}", sourceId);
            return new SourceFetchConfig(null, null, null, null, null);
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

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, string> rowFields)
    {
        var rowAsObjects = rowFields.ToDictionary(kv => kv.Key, kv => (object)kv.Value, StringComparer.OrdinalIgnoreCase);
        return BuildDocumentMetadataJson(linkMetadataJson, rowAsObjects);
    }

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, object> extractedFields)
    {
        var merged = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

        if (!string.IsNullOrWhiteSpace(linkMetadataJson))
        {
            try
            {
                using var doc = JsonDocument.Parse(linkMetadataJson);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                {
                    foreach (var property in doc.RootElement.EnumerateObject())
                    {
                        merged[property.Name] = ConvertJsonElementToObject(property.Value);
                    }
                }
            }
            catch (JsonException)
            {
                // Ignore malformed link metadata and fallback to row fields only.
            }
        }

        foreach (var (key, value) in extractedFields)
        {
            merged[key] = value;
        }

        return JsonSerializer.Serialize(merged);
    }

    public static string DeriveNormativeForce(IEnumerable<string> comentarios)
    {
        var joined = string.Join(" ", comentarios ?? []);
        if (string.IsNullOrWhiteSpace(joined))
            return "desconhecido";

        if (Regex.IsMatch(joined, "revoga", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "revogada";
        if (Regex.IsMatch(joined, "altera.{0,40}provis", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "modificada_provisoriamente";
        if (Regex.IsMatch(joined, "altera", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "modificada";

        return "desconhecido";
    }

    private static JsonElement? TryReadPath(JsonElement root, string path)
    {
        var current = root;
        foreach (var segment in path.Split('.', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var match = Regex.Match(segment, @"^(?<name>[^\[]+)(\[(?<index>\d+)\])?$");
            if (!match.Success)
                return null;

            var name = match.Groups["name"].Value;
            if (!current.TryGetProperty(name, out current))
                return null;

            if (match.Groups["index"].Success)
            {
                if (current.ValueKind != JsonValueKind.Array || !int.TryParse(match.Groups["index"].Value, out var idx))
                    return null;
                if (idx < 0 || idx >= current.GetArrayLength())
                    return null;
                current = current[idx];
            }
        }

        return current;
    }

    private static string? TryReadPathAsString(JsonElement root, string path)
    {
        var element = TryReadPath(root, path);
        if (!element.HasValue)
            return null;

        return element.Value.ValueKind switch
        {
            JsonValueKind.String => element.Value.GetString(),
            JsonValueKind.Number => element.Value.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => null
        };
    }

    private static IEnumerable<string> CollectComentarios(JsonElement? root)
    {
        if (!root.HasValue)
            yield break;

        foreach (var text in CollectComentariosRecursive(root.Value))
            yield return text;
    }

    /// <summary>
    /// Resets fetch items stuck in "processing" status from previous interrupted runs.
    /// This prevents stalls when jobs are cancelled mid-processing.
    /// Items are considered stuck if they've been in "processing" for more than 10 minutes
    /// without recent updates.
    /// </summary>
    private async Task<int> ResetStuckProcessingItemsAsync(string sourceId, CancellationToken ct)
    {
        try
        {
            var cutoffTime = DateTime.UtcNow.AddMinutes(-10);

            // Reset only stale "processing" items from previous interrupted runs.
            // Recent rows may belong to an active retry and must not be reclaimed.
            var stuckItems = await _context.FetchItems
                .Where(i => i.SourceId == sourceId
                    && i.Status == "processing"
                    && (i.UpdatedAt == null || i.UpdatedAt < cutoffTime))
                .ToListAsync(ct);
            
            if (stuckItems.Count == 0)
                return 0;

            foreach (var item in stuckItems)
            {
                item.Status = "pending";
                item.FetchRunId = null;
                item.LastError = "Reset processing item at fetch start";
                item.UpdatedAt = DateTime.UtcNow;
            }

            await _context.SaveChangesAsync(ct);
            return stuckItems.Count;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to reset stuck processing items for source {SourceId}", sourceId);
            return 0;
        }
    }

    private static IEnumerable<string> CollectComentariosRecursive(JsonElement node)
    {
        if (node.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in node.EnumerateObject())
            {
                if (prop.NameEquals("comentario") && prop.Value.ValueKind == JsonValueKind.String)
                {
                    var value = prop.Value.GetString();
                    if (!string.IsNullOrWhiteSpace(value))
                        yield return value!;
                }

                foreach (var nested in CollectComentariosRecursive(prop.Value))
                    yield return nested;
            }
        }
        else if (node.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in node.EnumerateArray())
            {
                foreach (var nested in CollectComentariosRecursive(item))
                    yield return nested;
            }
        }
    }

    private static object? ConvertJsonElementToObject(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number when value.TryGetInt64(out var i64) => i64,
            JsonValueKind.Number when value.TryGetDouble(out var dbl) => dbl,
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => null,
            JsonValueKind.Object => value.EnumerateObject()
                .ToDictionary(prop => prop.Name, prop => ConvertJsonElementToObject(prop.Value)),
            JsonValueKind.Array => value.EnumerateArray()
                .Select(ConvertJsonElementToObject)
                .ToList(),
            _ => value.GetRawText()
        };
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

    private async Task<IReadOnlyList<FetchItemEntity>> ClaimNextBatchWithRetryAsync(
        string sourceId,
        int limit,
        string[] statuses,
        Guid fetchRunId,
        string updatedBy,
        CancellationToken ct)
    {
        for (var attempt = 1; attempt <= ClaimBatchRetryAttempts; attempt++)
        {
            try
            {
                return await _fetchItemRepository.ClaimNextBatchAsync(
                    sourceId,
                    limit,
                    statuses,
                    fetchRunId,
                    updatedBy,
                    ct);
            }
            catch (Exception ex) when (IsTransientConnectionCapacity(ex) && attempt < ClaimBatchRetryAttempts)
            {
                var backoffMs = 250 * attempt;
                _logger.LogWarning(
                    ex,
                    "Transient DB capacity while claiming fetch batch for {SourceId} (attempt {Attempt}/{MaxAttempts}). Retrying in {BackoffMs}ms.",
                    sourceId,
                    attempt,
                    ClaimBatchRetryAttempts,
                    backoffMs);
                await Task.Delay(backoffMs, ct);
            }
        }

        return await _fetchItemRepository.ClaimNextBatchAsync(
            sourceId,
            limit,
            statuses,
            fetchRunId,
            updatedBy,
            ct);
    }

    private async Task SaveChangesWithRetryAsync(CancellationToken ct)
    {
        const int maxAttempts = 3;
        for (var attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                await _context.SaveChangesAsync(ct);
                return;
            }
            catch (Exception ex) when (IsTransientConnectionCapacity(ex) && attempt < maxAttempts)
            {
                var backoffMs = 200 * attempt;
                _logger.LogWarning(
                    ex,
                    "Transient DB capacity while saving fetch progress (attempt {Attempt}/{MaxAttempts}). Retrying in {BackoffMs}ms.",
                    attempt,
                    maxAttempts,
                    backoffMs);
                await Task.Delay(backoffMs, ct);
            }
        }

        await _context.SaveChangesAsync(ct);
    }

    private static bool IsTransientConnectionCapacity(Exception ex)
    {
        if (ex is NpgsqlException npgsql && npgsql.SqlState == "53300")
            return true;

        return ex.InnerException != null && IsTransientConnectionCapacity(ex.InnerException);
    }

    private static bool TryGetUnsupportedUrlScheme(string? url, out string scheme)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            scheme = "empty";
            return true;
        }

        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            scheme = "invalid";
            return true;
        }

        if (uri.Scheme.Equals(Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase)
            || uri.Scheme.Equals(Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
        {
            scheme = string.Empty;
            return false;
        }

        scheme = uri.Scheme.ToLowerInvariant();
        return true;
    }

    private static int ResolveLinkOnlyMaxBytes(string? envValue)
    {
        if (int.TryParse(envValue, out var parsed) && parsed > 0)
            return parsed;
        return DefaultLinkOnlyMaxBytes;
    }

    private static async Task<byte[]?> ReadAllBytesWithLimitAsync(Stream stream, int maxBytes, CancellationToken ct)
    {
        using var ms = new MemoryStream();
        var buffer = new byte[81920];
        while (true)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(0, buffer.Length), ct);
            if (read == 0)
                break;
            ms.Write(buffer, 0, read);
            if (ms.Length > maxBytes)
                return null;
        }

        return ms.ToArray();
    }

    private static string ResolveEffectiveFormat(string? formatType, string? contentType, string url)
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

    private static string ResolveConverterStrategy(string? configuredConverter, string effectiveFormat)
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

    private static LinkOnlyConversionResult ConvertLinkOnlyPayload(
        byte[] bytes,
        string strategy,
        string? contentType,
        string url)
    {
        return strategy switch
        {
            "html_to_text" => ConvertHtml(bytes, contentType),
            "json_to_text" => ConvertJson(bytes),
            "pdf_to_text_heuristic" => ConvertPdfHeuristic(bytes),
            "plain_text" => ConvertPlainText(bytes, contentType),
            _ => new LinkOnlyConversionResult(false, null, null, new Dictionary<string, object>(), $"unsupported_converter={strategy}")
        };
    }

    private static LinkOnlyConversionResult ConvertPlainText(byte[] bytes, string? contentType)
    {
        var text = DecodeBytesToString(bytes, contentType);
        text = TruncateText(Transforms.NormalizeWhitespace(text));
        return new LinkOnlyConversionResult(
            true,
            BuildTitleFromText(text),
            text,
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase));
    }

    private static LinkOnlyConversionResult ConvertHtml(byte[] bytes, string? contentType)
    {
        var html = DecodeBytesToString(bytes, contentType);
        var titleMatch = HtmlTitleRegex.Match(html);
        var title = titleMatch.Success
            ? Transforms.NormalizeWhitespace(Transforms.StripHtml(WebUtility.HtmlDecode(titleMatch.Groups["title"].Value)))
            : null;

        var cleaned = HtmlScriptStyleRegex.Replace(html, " ");
        var text = Transforms.NormalizeWhitespace(Transforms.StripHtml(cleaned));
        text = TruncateText(text);

        return new LinkOnlyConversionResult(
            true,
            string.IsNullOrWhiteSpace(title) ? BuildTitleFromText(text) : title,
            text,
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase));
    }

    private static LinkOnlyConversionResult ConvertJson(byte[] bytes)
    {
        try
        {
            using var doc = JsonDocument.Parse(bytes);
            var lines = new List<string>(512);
            var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            string? title = null;

            CollectJsonText(doc.RootElement, "$", lines, metadata, ref title, maxLines: 2000);
            var text = TruncateText(string.Join("\n", lines));
            title = FirstNonEmpty(
                title,
                metadata.TryGetValue("title", out var titleObj) ? titleObj?.ToString() : null,
                BuildTitleFromText(text));

            return new LinkOnlyConversionResult(true, title, text, metadata);
        }
        catch (Exception ex)
        {
            var raw = DecodeBytesToString(bytes, "application/json");
            if (raw.Contains("<html", StringComparison.OrdinalIgnoreCase)
                || raw.Contains("<!doctype", StringComparison.OrdinalIgnoreCase))
            {
                var fallback = ConvertHtml(bytes, "text/html; charset=utf-8");
                var metadata = new Dictionary<string, object>(fallback.Metadata, StringComparer.OrdinalIgnoreCase)
                {
                    ["json_parse_fallback"] = ex.GetType().Name
                };
                return fallback with { Metadata = metadata };
            }

            var fallbackText = TruncateText(Transforms.NormalizeWhitespace(raw));
            return new LinkOnlyConversionResult(
                true,
                BuildTitleFromText(fallbackText),
                fallbackText,
                new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                {
                    ["json_parse_fallback"] = ex.GetType().Name
                });
        }
    }

    private static void CollectJsonText(
        JsonElement element,
        string path,
        List<string> lines,
        Dictionary<string, object> metadata,
        ref string? title,
        int maxLines)
    {
        if (lines.Count >= maxLines)
            return;

        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
            {
                foreach (var prop in element.EnumerateObject())
                {
                    var nextPath = $"{path}.{prop.Name}";
                    if (prop.Value.ValueKind is JsonValueKind.String or JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False)
                    {
                        var normalized = NormalizeJsonScalar(prop.Value);
                        if (!string.IsNullOrWhiteSpace(normalized))
                        {
                            lines.Add($"{prop.Name}: {normalized}");
                            if (IsTitleKey(prop.Name) && string.IsNullOrWhiteSpace(title))
                                title = normalized;
                        }

                        if (metadata.Count < 100)
                            metadata[prop.Name] = normalized;
                    }
                    else
                    {
                        CollectJsonText(prop.Value, nextPath, lines, metadata, ref title, maxLines);
                    }

                    if (lines.Count >= maxLines)
                        break;
                }
                break;
            }
            case JsonValueKind.Array:
            {
                var index = 0;
                foreach (var item in element.EnumerateArray())
                {
                    CollectJsonText(item, $"{path}[{index}]", lines, metadata, ref title, maxLines);
                    index++;
                    if (lines.Count >= maxLines)
                        break;
                }
                break;
            }
            case JsonValueKind.String:
            case JsonValueKind.Number:
            case JsonValueKind.True:
            case JsonValueKind.False:
            {
                var scalar = NormalizeJsonScalar(element);
                if (!string.IsNullOrWhiteSpace(scalar))
                    lines.Add($"{path}: {scalar}");
                break;
            }
        }
    }

    private static string NormalizeJsonScalar(JsonElement element)
    {
        var raw = element.ValueKind switch
        {
            JsonValueKind.String => element.GetString() ?? string.Empty,
            JsonValueKind.Number => element.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => string.Empty
        };
        return TruncateText(Transforms.NormalizeWhitespace(raw), 2000);
    }

    private static bool IsTitleKey(string key)
    {
        var normalized = key.Trim().ToLowerInvariant();
        return normalized is "title" or "titulo" or "nome" or "ementa" or "normanome";
    }

    private static LinkOnlyConversionResult ConvertPdfHeuristic(byte[] bytes)
    {
        try
        {
            var raw = Encoding.Latin1.GetString(bytes);
            var snippets = new List<string>(256);

            foreach (Match match in PdfLiteralTextRegex.Matches(raw))
            {
                var decoded = DecodePdfLiteral(match.Groups["text"].Value);
                var normalized = Transforms.NormalizeWhitespace(decoded);
                if (normalized.Length >= 20)
                    snippets.Add(normalized);
                if (snippets.Count >= 500)
                    break;
            }

            if (snippets.Count < 50)
            {
                foreach (Match match in PdfArrayTextRegex.Matches(raw))
                {
                    foreach (Match literal in PdfArrayLiteralRegex.Matches(match.Groups["body"].Value))
                    {
                        var decoded = DecodePdfLiteral(literal.Groups["text"].Value);
                        var normalized = Transforms.NormalizeWhitespace(decoded);
                        if (normalized.Length >= 20)
                            snippets.Add(normalized);
                        if (snippets.Count >= 500)
                            break;
                    }

                    if (snippets.Count >= 500)
                        break;
                }
            }

            if (snippets.Count == 0)
            {
                foreach (Match match in PrintableSequenceRegex.Matches(raw))
                {
                    var normalized = Transforms.NormalizeWhitespace(match.Value);
                    if (normalized.Length >= 30)
                        snippets.Add(normalized);
                    if (snippets.Count >= 200)
                        break;
                }
            }

            var uniqueSnippets = snippets
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(500)
                .ToList();
            var text = TruncateText(string.Join("\n", uniqueSnippets));

            return new LinkOnlyConversionResult(
                true,
                BuildTitleFromText(text),
                text,
                new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                {
                    ["pdf_extractor"] = "heuristic"
                });
        }
        catch (Exception ex)
        {
            return new LinkOnlyConversionResult(false, null, null, new Dictionary<string, object>(), $"pdf_parse_error={ex.GetType().Name}");
        }
    }

    private static string DecodePdfLiteral(string value)
    {
        var result = value
            .Replace("\\n", " ")
            .Replace("\\r", " ")
            .Replace("\\t", " ")
            .Replace("\\(", "(")
            .Replace("\\)", ")")
            .Replace("\\\\", "\\");
        return result;
    }

    private static string DecodeBytesToString(byte[] bytes, string? contentType)
    {
        var charset = TryExtractCharset(contentType);
        if (!string.IsNullOrWhiteSpace(charset))
        {
            try
            {
                return Encoding.GetEncoding(charset!).GetString(bytes);
            }
            catch
            {
                // fallback below
            }
        }

        try
        {
            return Encoding.UTF8.GetString(bytes);
        }
        catch
        {
            return Encoding.Latin1.GetString(bytes);
        }
    }

    private static string? TryExtractCharset(string? contentType)
    {
        if (string.IsNullOrWhiteSpace(contentType))
            return null;

        var marker = "charset=";
        var index = contentType.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
            return null;

        var value = contentType[(index + marker.Length)..].Trim();
        var semicolon = value.IndexOf(';');
        if (semicolon >= 0)
            value = value[..semicolon];
        return value.Trim('"', '\'');
    }

    private static string TruncateText(string text, int maxChars = DefaultMaxConvertedTextChars)
    {
        if (string.IsNullOrEmpty(text))
            return string.Empty;
        if (text.Length <= maxChars)
            return text;
        return text[..maxChars];
    }

    private static string? BuildTitleFromText(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return null;
        var firstLine = text.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).FirstOrDefault();
        if (string.IsNullOrWhiteSpace(firstLine))
            return null;
        return firstLine!.Length <= 180 ? firstLine : firstLine[..180];
    }

    private static string? TryReadMetadataValueAsString(string? linkMetadataJson, string key)
    {
        if (string.IsNullOrWhiteSpace(linkMetadataJson))
            return null;

        try
        {
            using var doc = JsonDocument.Parse(linkMetadataJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
                return null;

            if (!doc.RootElement.TryGetProperty(key, out var value))
                return null;

            return value.ValueKind switch
            {
                JsonValueKind.String => value.GetString(),
                JsonValueKind.Number => value.GetRawText(),
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                _ => null
            };
        }
        catch
        {
            return null;
        }
    }

    private static string? FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value;
        }

        return null;
    }

    private async Task<int> ReleaseCappedProcessingItemsAsync(string sourceId, Guid fetchRunId, CancellationToken ct)
    {
        var updatedAt = DateTime.UtcNow;
        return await _context.Database.ExecuteSqlInterpolatedAsync($"""
            UPDATE fetch_items
            SET "Status" = 'pending',
                "FetchRunId" = NULL,
                "LastError" = 'deferred_due_to_max_docs_cap',
                "CompletedAt" = NULL,
                "UpdatedAt" = {updatedAt}
            WHERE "SourceId" = {sourceId}
              AND "Status" = 'processing'
              AND "FetchRunId" = {fetchRunId}
            """, ct);
    }

    private static void MarkDeferredByCap(FetchItemEntity item)
    {
        item.Status = "pending";
        item.FetchRunId = null;
        item.LastError = "deferred_due_to_max_docs_cap";
        item.CompletedAt = null;
        item.UpdatedAt = DateTime.UtcNow;
    }

    private record FetchResult
    {
        public bool SkippedUnchanged { get; init; }
        public bool SkippedFormat { get; init; }
        public string? ErrorDetail { get; init; }
        public int RowsProcessed { get; init; }
        public int DocumentsCreated { get; init; }
        public int TruncatedFields { get; init; }
        public bool Capped { get; init; }
        public string? NewEtag { get; init; }
        public string? NewLastModified { get; init; }
    }

    private sealed class JsonApiExtractConfig
    {
        public string? TitlePath { get; init; }
        public string? ContentPath { get; init; }
        public string? IdPath { get; init; }
        public string? VidesPath { get; init; }
    }

    private sealed record SourceFetchConfig(
        JsonElement? ParseConfig,
        string? ContentStrategy,
        string? FormatType,
        string? Converter,
        JsonApiExtractConfig? JsonApiExtract);

    private sealed record LinkOnlyConversionResult(
        bool Success,
        string? Title,
        string? Content,
        IReadOnlyDictionary<string, object> Metadata,
        string? ErrorDetail = null);
}
