using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Fetch;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs.Fetch;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;

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
    private readonly IFetchUrlValidator _fetchUrlValidator;
    private readonly IJobQueueRepository _jobQueue;
    private readonly IConfiguration _configuration;
    private readonly ILogger<FetchJobExecutor> _logger;
    private readonly HttpClient _httpClient;
    private const int BatchSize = 25;
    private const int FetchCandidatePageSize = 100;
    public const int DefaultMaxFieldLength = 262_144;

    public FetchJobExecutor(
        GabiDbContext context,
        IFetchItemRepository fetchItemRepository,
        IFetchUrlValidator fetchUrlValidator,
        IJobQueueRepository jobQueue,
        IConfiguration configuration,
        ILogger<FetchJobExecutor> logger)
    {
        _context = context;
        _fetchItemRepository = fetchItemRepository;
        _fetchUrlValidator = fetchUrlValidator;
        _jobQueue = jobQueue;
        _configuration = configuration;
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
        var maxDocsPerSource = FetchPayloadOptions.ReadMaxDocsPerSource(job.Payload);
        var strictCoverage = FetchPayloadOptions.ReadStrictCoverage(job.Payload);
        activity?.SetTag("coverage.strict", strictCoverage);

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
            return new JobResult { Status = JobTerminalStatus.Failed, ErrorMessage = $"Source {sourceId} not found" };
        }

        var persistence = new FetchBatchPersistence(_context, _fetchItemRepository, _jobQueue, _logger);

        // Cleanup: reset items stuck in "processing" from previous interrupted runs
        // This prevents stalls when jobs are cancelled mid-processing
        var stuckItemsReset = await persistence.ResetStuckProcessingItemsAsync(sourceId, ct);
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
            return new JobResult { Status = JobTerminalStatus.Success };
        }

        if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
        {
            _logger.LogInformation("Fetch skipped for {SourceId}: source is paused or stopped", sourceId);
            fetchRun.CompletedAt = DateTime.UtcNow;
            fetchRun.Status = "completed";
            fetchRun.ItemsTotal = total;
            await _context.SaveChangesAsync(ct);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object> { ["interrupted_by"] = "pause", ["documents_created"] = 0 }
            };
        }

        var backpressure = PipelineBackpressureConfig.Load();
        var pendingIngest = await _context.Documents.CountAsync(d => d.SourceId == sourceId && d.Status == "pending", ct);
        if (pendingIngest > backpressure.MaxPendingIngest)
        {
            _logger.LogInformation(
                "Fetch yielding for {SourceId}: backpressure pending_ingest={Pending} > {Max}",
                sourceId, pendingIngest, backpressure.MaxPendingIngest);
            fetchRun.CompletedAt = DateTime.UtcNow;
            fetchRun.Status = "completed";
            fetchRun.ItemsTotal = total;
            await _context.SaveChangesAsync(ct);
            var retryJob = new IngestJob
            {
                Id = Guid.NewGuid(),
                SourceId = sourceId,
                JobType = "fetch",
                Payload = job.Payload ?? new Dictionary<string, object>()
            };
            await _jobQueue.ScheduleAsync(retryJob, TimeSpan.FromSeconds(60), ct);
            return new JobResult
            {
                Status = JobTerminalStatus.Success,
                Metadata = new Dictionary<string, object>
                {
                    ["yielded"] = true,
                    ["reason"] = "backpressure",
                    ["pending_downstream"] = pendingIngest
                }
            };
        }

        if (maxDocsPerSource.HasValue)
        {
            _logger.LogInformation(
                "Fetch cap enabled for {SourceId}: max_docs_per_source={MaxDocs}",
                sourceId,
                maxDocsPerSource.Value);
        }

        var sourceFetchConfig = await FetchSourceConfigLoader.LoadSourceFetchConfigAsync(sourceId, _configuration, ct);
        var parseConfig = sourceFetchConfig.ParseConfig;
        var fetchContentStrategy = sourceFetchConfig.ContentStrategy;
        var jsonApiExtractConfig = sourceFetchConfig.JsonApiExtract;
        var fetchFormatType = sourceFetchConfig.FormatType;
        var fetchConverter = sourceFetchConfig.Converter;
        var maxFieldLength = FetchSourceConfigLoader.ResolveMaxFieldLength(parseConfig, Environment.GetEnvironmentVariable("GABI_FETCH_MAX_FIELD_CHARS"));
        var telemetryEveryRows = FetchSourceConfigLoader.ResolveTelemetryEveryRows(Environment.GetEnvironmentVariable("GABI_FETCH_TELEMETRY_EVERY_ROWS"));
        var linkOnlyMaxBytes = FetchSourceConfigLoader.ResolveLinkOnlyMaxBytes(Environment.GetEnvironmentVariable("GABI_FETCH_LINK_ONLY_MAX_BYTES"));
        var csvConfig = FetchSourceConfigLoader.GetCsvFormatConfig(source);

        var completed = 0;
        var failed = 0;
        var totalDocs = 0;
        var totalRows = 0;
        var capped = false;
        var totalTruncatedFields = 0;

        if (string.Equals(fetchContentStrategy, "link_only", StringComparison.OrdinalIgnoreCase))
        {
            var processed = 0;
            var interruptedByPause = false;
            while (true)
            {
                if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
                {
                    _logger.LogInformation("Fetch interrupted for {SourceId}: source paused/stopped (link_only)", sourceId);
                    interruptedByPause = true;
                    break;
                }
                if (IsCapReached(totalDocs, maxDocsPerSource))
                {
                    capped = true;
                    break;
                }

                var pageItems = await persistence.ClaimNextBatchWithRetryAsync(
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
                        FetchBatchPersistence.MarkDeferredByCap(item);
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
                        else if (!await _fetchUrlValidator.IsUrlAllowedAsync(item.Url, ct))
                        {
                            item.Status = "skipped";
                            item.LastError = "url_blocked_ssrf";
                            item.CompletedAt = DateTime.UtcNow;
                            completed++;
                            processed++;
                            _logger.LogWarning("Fetch skipped (URL blocked by SSRF policy): {Url}", item.Url);
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
                                persistence,
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

                await persistence.SaveChangesWithRetryAsync(ct);
                _context.ChangeTracker.Clear();
                if (stopAfterCurrentBatch)
                    break;
            }

            if (maxDocsPerSource.HasValue && (capped || processed >= maxDocsPerSource.Value))
            {
                var released = await persistence.ReleaseCappedProcessingItemsAsync(sourceId, fetchRun.Id, ct);
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

            var linkOnlyMetadata = new Dictionary<string, object>
            {
                ["fetch_run_id"] = fetchRun.Id.ToString(),
                ["items_total"] = total,
                ["items_completed"] = completed,
                ["items_failed"] = failed,
                ["documents_created"] = totalDocs,
                ["rows_processed"] = totalRows,
                ["fields_truncated"] = 0,
                ["capped"] = capped,
                ["content_strategy"] = "link_only",
                ["strict_coverage"] = strictCoverage
            };
            if (interruptedByPause)
            {
                linkOnlyMetadata["interrupted_by"] = "pause";
                linkOnlyMetadata["last_cursor"] = totalDocs;
            }
            return new JobResult
            {
                Status = ResolveFetchTerminalStatus(failed, total, capped),
                Metadata = linkOnlyMetadata
            };
        }

        var processedCount = 0;
        var interruptedByPauseMain = false;
        while (true)
        {
            if (await _context.IsSourcePausedOrStoppedAsync(sourceId, ct))
            {
                _logger.LogInformation("Fetch interrupted for {SourceId}: source paused/stopped at {Processed} items", sourceId, processedCount);
                interruptedByPauseMain = true;
                break;
            }
            if (capped || IsCapReached(totalDocs, maxDocsPerSource))
            {
                capped = true;
                break;
            }

            var pageItems = await persistence.ClaimNextBatchWithRetryAsync(
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
                    FetchBatchPersistence.MarkDeferredByCap(item);
                    await persistence.SaveChangesWithRetryAsync(ct);
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
                    else if (!await _fetchUrlValidator.IsUrlAllowedAsync(item.Url, ct))
                    {
                        item.Status = "skipped";
                        item.LastError = "url_blocked_ssrf";
                        item.CompletedAt = DateTime.UtcNow;
                        completed++;
                        _logger.LogWarning("Fetch skipped (URL blocked by SSRF policy): {Url}", item.Url);
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
                                persistence,
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
                                persistence,
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
                await persistence.SaveChangesWithRetryAsync(ct);

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
            var released = await persistence.ReleaseCappedProcessingItemsAsync(sourceId, fetchRun.Id, ct);
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

        var mainMetadata = new Dictionary<string, object>
        {
            ["fetch_run_id"] = fetchRun.Id.ToString(),
            ["items_total"] = total,
            ["items_completed"] = completed,
            ["items_failed"] = failed,
            ["documents_created"] = totalDocs,
            ["rows_processed"] = totalRows,
            ["fields_truncated"] = totalTruncatedFields,
            ["capped"] = capped,
            ["strict_coverage"] = strictCoverage
        };
        if (interruptedByPauseMain)
        {
            mainMetadata["interrupted_by"] = "pause";
            mainMetadata["last_cursor"] = totalDocs;
        }
        return new JobResult
        {
            Status = ResolveFetchTerminalStatus(failed, total, capped),
            Metadata = mainMetadata
        };
    }

    private static JobTerminalStatus ResolveFetchTerminalStatus(int failed, int total, bool capped)
    {
        if (failed == total) return JobTerminalStatus.Failed;
        if (failed > 0) return JobTerminalStatus.Partial;
        if (capped) return JobTerminalStatus.Capped;
        return JobTerminalStatus.Success;
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
        FetchBatchPersistence persistence,
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

        var effectiveFormat = FetchSourceConfigLoader.ResolveEffectiveFormat(formatType, contentType, url);
        var strategy = FetchSourceConfigLoader.ResolveConverterStrategy(converter, effectiveFormat);
        var conversion = FetchContentConverter.ConvertLinkOnlyPayload(bytes, strategy, contentType, url);

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

        var docId = FetchContentConverter.FirstNonEmpty(
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "document_id"),
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "id"),
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "key"));

        var externalId = FetchContentConverter.FirstNonEmpty(
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "external_id"),
            docId,
            ComputeHash(new Dictionary<string, string> { ["url"] = url }));

        var title = FetchContentConverter.FirstNonEmpty(
            conversion.Title,
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "title"),
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "titulo"),
            FetchFieldExtractor.TryReadMetadataValueAsString(linkMetadataJson, "nome"));

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
            Metadata = FetchFieldExtractor.BuildDocumentMetadataJson(linkMetadataJson, metadataAsObjects)
        };

        await persistence.InsertBatchAsync([docEntity], ct);
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
        FetchBatchPersistence persistence,
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
            persistence,
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
        FetchBatchPersistence persistence,
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
                var docId = FetchFieldExtractor.ExtractDocumentId(row.Fields, parseConfig);
                var externalId = docId ?? $"row-{rowsProcessed}";

                var doc = new DocumentEntity
                {
                    LinkId = item.DiscoveredLinkId,
                    FetchItemId = item.Id,
                    SourceId = sourceId,
                    ExternalId = externalId,
                    DocumentId = docId,
                    Title = FetchFieldExtractor.ExtractTitle(row.Fields, parseConfig),
                    Content = FetchFieldExtractor.ExtractContent(row.Fields, parseConfig),
                    ContentHash = ComputeHash(row.Fields),
                    Status = "pending",
                    ProcessingStage = "fetch_completed",
                    Metadata = FetchFieldExtractor.BuildDocumentMetadataJson(linkMetadataJson, row.Fields)
                };

                batch.Add(doc);
                documentsCreated++;

                if (batch.Count >= BatchSize)
                {
                    await persistence.InsertBatchAsync(batch, ct);
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
            await persistence.InsertBatchAsync(batch, ct);
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
        FetchBatchPersistence persistence,
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

        var extractedTitle = FetchFieldExtractor.TryReadPathAsString(doc.RootElement, titlePath);
        var extractedContent = FetchFieldExtractor.TryReadPathAsString(doc.RootElement, contentPath);
        var extractedId = FetchFieldExtractor.TryReadPathAsString(doc.RootElement, idPath);
        var videsElement = FetchFieldExtractor.TryReadPath(doc.RootElement, videsPath);
        var normativeForce = FetchFieldExtractor.DeriveNormativeForce(FetchFieldExtractor.CollectComentarios(videsElement));

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
            : ComputeHash(new Dictionary<string, string> { ["url"] = url });

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
            Metadata = FetchFieldExtractor.BuildDocumentMetadataJson(linkMetadataJson, extractedMetadata)
        };

        await persistence.InsertBatchAsync([docEntity], ct);

        return new FetchResult
        {
            DocumentsCreated = 1,
            RowsProcessed = 1,
            NewEtag = newEtag,
            NewLastModified = newLastModified
        };
    }

    private static string ComputeHash(Dictionary<string, string> fields)
    {
        var content = string.Join("|", fields.Values);
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, string> rowFields)
        => FetchFieldExtractor.BuildDocumentMetadataJson(linkMetadataJson, rowFields);

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, object> extractedFields)
        => FetchFieldExtractor.BuildDocumentMetadataJson(linkMetadataJson, extractedFields);

    public static string DeriveNormativeForce(IEnumerable<string> comentarios)
        => FetchFieldExtractor.DeriveNormativeForce(comentarios);


    public static int? ReadMaxDocsPerSource(Dictionary<string, object>? payload)
        => FetchPayloadOptions.ReadMaxDocsPerSource(payload);

    public static bool ReadStrictCoverage(Dictionary<string, object>? payload)
        => FetchPayloadOptions.ReadStrictCoverage(payload);

    /// <summary>Reads min_coverage_ratio from job payload (0.0–1.0; default 0.5). Used for discovery coverage gate.</summary>
    public static double ReadMinCoverageRatio(Dictionary<string, object>? payload)
        => FetchPayloadOptions.ReadMinCoverageRatio(payload);

    /// <summary>Reads zero_ok from job payload (when true, 0 links discovered is accepted; default false).</summary>
    public static bool ReadZeroOk(Dictionary<string, object>? payload)
        => FetchPayloadOptions.ReadZeroOk(payload);

    public static bool IsCapReached(int documentsCreated, int? maxDocsPerSource)
    {
        return maxDocsPerSource.HasValue && documentsCreated >= maxDocsPerSource.Value;
    }

    /// <summary>Delegates to FetchSourceConfigLoader.ResolveMaxFieldLength for public backward-compat callers.</summary>
    public static int ResolveMaxFieldLength(JsonElement? parseConfig, string? envValue)
        => FetchSourceConfigLoader.ResolveMaxFieldLength(parseConfig, envValue);

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

}

