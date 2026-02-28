using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Api;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Pipeline;
using Microsoft.Extensions.Logging;

namespace Gabi.Sync.Phase0;

/// <summary>
/// Orquestrador do Phase 0: Discovery + Metadata + Comparison.
/// </summary>
public class Phase0Orchestrator : IPhase0Orchestrator
{
    private readonly ISourceCatalog _sourceCatalog;
    private readonly IDiscoveryEngine _discoveryEngine;
    private readonly IPhase0LinkComparator _linkComparator;
    private readonly IMetadataFetcher _metadataFetcher;
    private readonly IPhase0LinkRepository _linkRepository;
    private readonly ILogger<Phase0Orchestrator> _logger;

    public Phase0Orchestrator(
        ISourceCatalog sourceCatalog,
        IDiscoveryEngine discoveryEngine,
        IPhase0LinkComparator linkComparator,
        IMetadataFetcher metadataFetcher,
        IPhase0LinkRepository linkRepository,
        ILogger<Phase0Orchestrator> logger)
    {
        _sourceCatalog = sourceCatalog ?? throw new ArgumentNullException(nameof(sourceCatalog));
        _discoveryEngine = discoveryEngine ?? throw new ArgumentNullException(nameof(discoveryEngine));
        _linkComparator = linkComparator ?? throw new ArgumentNullException(nameof(linkComparator));
        _metadataFetcher = metadataFetcher ?? throw new ArgumentNullException(nameof(metadataFetcher));
        _linkRepository = linkRepository ?? throw new ArgumentNullException(nameof(linkRepository));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    public async Task<Phase0Result> RunAsync(string sourceId, Phase0Options options, CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        
        try
        {
            _logger.LogInformation("Starting Phase 0 for source {SourceId}", sourceId);

            // 1. Get Source Definition
            var source = await _sourceCatalog.GetSourceAsync(sourceId, ct);
            if (source == null)
            {
                _logger.LogError("Source {SourceId} not found", sourceId);
                return new Phase0Result
                {
                    SourceId = sourceId,
                    Success = false,
                    ErrorMessage = $"Source '{sourceId}' not found",
                    StartedAt = startedAt,
                    CompletedAt = DateTime.UtcNow
                };
            }

            // 2. DISCOVERY - Run DiscoveryEngine to get all DiscoveredSources
            var discoveryConfig = source.DiscoveryConfig ?? new DiscoveryConfig { Mode = DiscoveryMode.StaticUrl };
            var discoveredSources = await RunDiscoveryAsync(sourceId, discoveryConfig, options, ct);
            _logger.LogInformation("Discovered {Count} links for {SourceId}", discoveredSources.Count, sourceId);

            // 3. COMPARISON - Check each link against database
            var comparisonResults = await RunComparisonAsync(sourceId, discoveredSources, options, ct);

            // 4. METADATA FETCH - Fetch metadata for new/changed links
            var linksWithMetadata = await FetchMetadataAsync(discoveredSources, comparisonResults, options, ct);

            // 5. PERSIST - Insert/update links in database
            await PersistLinksAsync(linksWithMetadata, ct);

            // 6. Build result
            var result = BuildResult(sourceId, startedAt, discoveredSources, linksWithMetadata);
            
            _logger.LogInformation(
                "Phase 0 completed for {SourceId}: {New} new, {Updated} updated, {Skipped} skipped, {ToProcess} to process",
                sourceId,
                result.NewLinksCount,
                result.UpdatedLinksCount,
                result.SkippedLinksCount,
                result.LinksToProcess.Count);

            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Phase 0 failed for source {SourceId}", sourceId);
            return new Phase0Result
            {
                SourceId = sourceId,
                Success = false,
                ErrorMessage = ex.Message,
                StartedAt = startedAt,
                CompletedAt = DateTime.UtcNow
            };
        }
    }

    private async Task<IReadOnlyList<DiscoveredSource>> RunDiscoveryAsync(
        string sourceId,
        DiscoveryConfig config,
        Phase0Options options,
        CancellationToken ct)
    {
        var results = new List<DiscoveredSource>();
        var count = 0;

        await foreach (var source in _discoveryEngine.DiscoverAsync(sourceId, config, ct))
        {
            results.Add(source);
            count++;

            if (options.MaxLinks.HasValue && count >= options.MaxLinks.Value)
            {
                _logger.LogInformation("Max links limit ({MaxLinks}) reached for {SourceId}", options.MaxLinks, sourceId);
                break;
            }
        }

        return results;
    }

    private async Task<IReadOnlyList<Phase0LinkComparisonResult>> RunComparisonAsync(
        string sourceId,
        IReadOnlyList<DiscoveredSource> discoveredSources,
        Phase0Options options,
        CancellationToken ct)
    {
        var results = new List<Phase0LinkComparisonResult>();

        foreach (var discovered in discoveredSources)
        {
            ct.ThrowIfCancellationRequested();

            // Check if link exists in database (returns Contracts type directly)
            var existingLink = await _linkRepository.GetBySourceAndUrlAsync(sourceId, discovered.Url, ct);

            // If not exists, mark as new
            if (existingLink == null)
            {
                results.Add(new Phase0LinkComparisonResult
                {
                    Status = LinkDiscoveryStatus.New,
                    Reason = "new_link",
                    UpdatedLink = new Contracts.Pipeline.DiscoveredLinkPhase0
                    {
                        SourceId = sourceId,
                        Url = discovered.Url,
                        UrlHash = ComputeHash(discovered.Url),
                        Status = LinkDiscoveryStatus.New
                    }
                });
                continue;
            }

            // Existing link - always check for changes by fetching metadata
            // (LinkComparator will decide if it's changed or unchanged)
            results.Add(new Phase0LinkComparisonResult
            {
                Status = LinkDiscoveryStatus.Changed, // Tentative, will be refined after metadata fetch
                Reason = "existing_check",
                UpdatedLink = existingLink
            });
        }

        return results;
    }

    private async Task<IReadOnlyList<Contracts.Pipeline.DiscoveredLinkPhase0>> FetchMetadataAsync(
        IReadOnlyList<DiscoveredSource> discoveredSources,
        IReadOnlyList<Phase0LinkComparisonResult> comparisonResults,
        Phase0Options options,
        CancellationToken ct)
    {
        // Create a lookup from URL to DiscoveredSource for comparison
        var sourceLookup = discoveredSources.ToDictionary(s => s.Url);

        // Only fetch metadata for new or changed links
        var linksToFetch = comparisonResults
            .Where(r => r.Status is LinkDiscoveryStatus.New or LinkDiscoveryStatus.Changed)
            .Select(r => r.UpdatedLink)
            .ToList();

        if (linksToFetch.Count == 0)
        {
            return comparisonResults.Select(r => r.UpdatedLink).ToList();
        }

        var fetchedResults = new ConcurrentBag<(Contracts.Pipeline.DiscoveredLinkPhase0 Link, DiscoveredSource Source, MetadataFetchResult Metadata)>();

        if (options.ParallelMetadataFetch)
        {
            var semaphore = new SemaphoreSlim(options.MaxParallelism);
            var tasks = linksToFetch.Select(async link =>
            {
                await semaphore.WaitAsync(ct);
                try
                {
                    var metadata = await FetchMetadataForLinkAsync(link.Url, options.MetadataFetchTimeout, ct);
                    var source = sourceLookup.GetValueOrDefault(link.Url);
                    fetchedResults.Add((link, source!, metadata));
                }
                finally
                {
                    semaphore.Release();
                }
            });

            await Task.WhenAll(tasks);
        }
        else
        {
            foreach (var link in linksToFetch)
            {
                ct.ThrowIfCancellationRequested();
                var metadata = await FetchMetadataForLinkAsync(link.Url, options.MetadataFetchTimeout, ct);
                var source = sourceLookup.GetValueOrDefault(link.Url);
                fetchedResults.Add((link, source!, metadata));
            }
        }

        // Use LinkComparator to determine final status
        var finalLinks = new List<Contracts.Pipeline.DiscoveredLinkPhase0>();
        
        foreach (var (existingLink, source, metadata) in fetchedResults)
        {
            var comparison = _linkComparator.Compare(source, existingLink, metadata);
            finalLinks.Add(comparison.UpdatedLink);
        }

        // Add unchanged links that were skipped from metadata fetching
        var unchangedLinks = comparisonResults
            .Where(r => r.Status == LinkDiscoveryStatus.Unchanged)
            .Select(r => r.UpdatedLink);
        finalLinks.AddRange(unchangedLinks);

        return finalLinks;
    }

    private async Task<MetadataFetchResult> FetchMetadataForLinkAsync(
        string url,
        TimeSpan timeout,
        CancellationToken ct)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(timeout);

            var metadata = await _metadataFetcher.FetchAsync(url, cts.Token);

            if (!metadata.Success)
            {
                _logger.LogWarning("Failed to fetch metadata for {Url}: {Error}", url, metadata.ErrorMessage);
            }

            return metadata;
        }
        catch (OperationCanceledException)
        {
            _logger.LogWarning("Metadata fetch timed out for {Url}", url);
            return new MetadataFetchResult { Success = false, ErrorMessage = "Timeout" };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error fetching metadata for {Url}", url);
            return new MetadataFetchResult { Success = false, ErrorMessage = ex.Message };
        }
    }

    private async Task PersistLinksAsync(
        IReadOnlyList<Contracts.Pipeline.DiscoveredLinkPhase0> links,
        CancellationToken ct)
    {
        // Only persist new or changed links
        var linksToPersist = links
            .Where(l => l.Status is LinkDiscoveryStatus.New or LinkDiscoveryStatus.Changed or LinkDiscoveryStatus.MarkedForProcessing)
            .ToList();

        if (linksToPersist.Count == 0)
        {
            return;
        }

        await _linkRepository.BulkUpsertAsync(linksToPersist, ct);
        _logger.LogInformation("Persisted {Count} links to database", linksToPersist.Count);
    }

    private Phase0Result BuildResult(
        string sourceId,
        DateTime startedAt,
        IReadOnlyList<DiscoveredSource> discoveredSources,
        IReadOnlyList<Contracts.Pipeline.DiscoveredLinkPhase0> links)
    {
        var newLinks = links.Where(l => l.Status == LinkDiscoveryStatus.New).ToList();
        var changedLinks = links.Where(l => l.Status == LinkDiscoveryStatus.Changed).ToList();
        var unchangedLinks = links.Where(l => l.Status == LinkDiscoveryStatus.Unchanged).ToList();

        // Links to process in Phase 1: new + changed
        var linksToProcess = links
            .Where(l => l.Status is LinkDiscoveryStatus.New or LinkDiscoveryStatus.Changed)
            .Select(l => l with { Status = LinkDiscoveryStatus.MarkedForProcessing })
            .ToList();

        var totalSize = links
            .Where(l => l.ContentLength.HasValue)
            .Sum(l => l.ContentLength.Value);

        var totalDocs = links
            .Where(l => l.EstimatedDocumentCount.HasValue)
            .Sum(l => l.EstimatedDocumentCount.Value);

        return new Phase0Result
        {
            SourceId = sourceId,
            Success = true,
            StartedAt = startedAt,
            CompletedAt = DateTime.UtcNow,
            DiscoveredLinksCount = discoveredSources.Count,
            MetadataFetchedCount = newLinks.Count + changedLinks.Count,
            TotalEstimatedSizeBytes = totalSize,
            TotalEstimatedDocuments = totalDocs > 0 ? totalDocs : null,
            NewLinksCount = newLinks.Count,
            UpdatedLinksCount = changedLinks.Count,
            SkippedLinksCount = unchangedLinks.Count,
            LinksToProcess = linksToProcess
        };
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = SHA256.Create();
        var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// Default implementation of IPhase0LinkComparator.
/// </summary>
public class LinkComparator : IPhase0LinkComparator
{
    public Phase0LinkComparisonResult Compare(
        DiscoveredSource discovered,
        Contracts.Pipeline.DiscoveredLinkPhase0? existing,
        MetadataFetchResult? fetchedMetadata)
    {
        // New link (null or Id = 0 indicates not yet persisted)
        if (existing == null || existing.Id == 0)
        {
            return new Phase0LinkComparisonResult
            {
                Status = LinkDiscoveryStatus.New,
                Reason = "new_link",
                UpdatedLink = new Contracts.Pipeline.DiscoveredLinkPhase0
                {
                    SourceId = discovered.SourceId,
                    Url = discovered.Url,
                    UrlHash = ComputeHash(discovered.Url),
                    Etag = fetchedMetadata?.Etag,
                    LastModified = fetchedMetadata?.LastModified,
                    ContentLength = fetchedMetadata?.ContentLength,
                    Status = LinkDiscoveryStatus.New,
                    Metadata = discovered.Metadata
                }
            };
        }

        // Check if metadata changed
        var etagChanged = fetchedMetadata?.Etag != null && fetchedMetadata.Etag != existing.Etag;
        var lastModifiedChanged = fetchedMetadata?.LastModified.HasValue == true && 
                                   fetchedMetadata.LastModified != existing.LastModified;
        var contentLengthChanged = fetchedMetadata?.ContentLength.HasValue == true &&
                                    fetchedMetadata.ContentLength != existing.ContentLength;

        if (etagChanged || lastModifiedChanged || contentLengthChanged)
        {
            return new Phase0LinkComparisonResult
            {
                Status = LinkDiscoveryStatus.Changed,
                Reason = etagChanged ? "etag_changed" : lastModifiedChanged ? "last_modified_changed" : "content_length_changed",
                UpdatedLink = existing with
                {
                    Etag = fetchedMetadata?.Etag ?? existing.Etag,
                    LastModified = fetchedMetadata?.LastModified ?? existing.LastModified,
                    ContentLength = fetchedMetadata?.ContentLength ?? existing.ContentLength,
                    Status = LinkDiscoveryStatus.Changed
                }
            };
        }

        // No changes
        return new Phase0LinkComparisonResult
        {
            Status = LinkDiscoveryStatus.Unchanged,
            Reason = "no_changes",
            UpdatedLink = existing
        };
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = SHA256.Create();
        var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// Default implementation of IMetadataFetcher using HttpClient.
/// </summary>
public class HttpMetadataFetcher : IMetadataFetcher
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<HttpMetadataFetcher> _logger;

    public HttpMetadataFetcher(HttpClient httpClient, ILogger<HttpMetadataFetcher> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<MetadataFetchResult> FetchAsync(string url, CancellationToken ct = default)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Head, url);
            var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);

            if (!response.IsSuccessStatusCode)
            {
                // Try GET if HEAD is not allowed
                if (response.StatusCode == System.Net.HttpStatusCode.MethodNotAllowed)
                {
                    return await FetchWithGetAsync(url, ct);
                }

                return new MetadataFetchResult
                {
                    Success = false,
                    ErrorMessage = $"HTTP {(int)response.StatusCode}: {response.ReasonPhrase}"
                };
            }

            return ExtractMetadata(response);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to fetch metadata for {Url}", url);
            return new MetadataFetchResult
            {
                Success = false,
                ErrorMessage = ex.Message
            };
        }
    }

    private async Task<MetadataFetchResult> FetchWithGetAsync(string url, CancellationToken ct)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);

            if (!response.IsSuccessStatusCode)
            {
                return new MetadataFetchResult
                {
                    Success = false,
                    ErrorMessage = $"HTTP {(int)response.StatusCode}: {response.ReasonPhrase}"
                };
            }

            // Dispose content immediately - we only need headers
            response.Content?.Dispose();

            return ExtractMetadata(response);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to fetch metadata with GET for {Url}", url);
            return new MetadataFetchResult
            {
                Success = false,
                ErrorMessage = ex.Message
            };
        }
    }

    private static MetadataFetchResult ExtractMetadata(HttpResponseMessage response)
    {
        long? contentLength = null;
        if (response.Content.Headers.ContentLength.HasValue)
        {
            contentLength = response.Content.Headers.ContentLength.Value;
        }

        DateTime? lastModified = null;
        if (response.Content.Headers.LastModified.HasValue)
        {
            lastModified = response.Content.Headers.LastModified.Value.UtcDateTime;
        }

        var etag = response.Headers.ETag?.Tag;
        var contentType = response.Content.Headers.ContentType?.MediaType;

        return new MetadataFetchResult
        {
            Success = true,
            ContentLength = contentLength,
            LastModified = lastModified,
            Etag = etag,
            ContentType = contentType
        };
    }
}
