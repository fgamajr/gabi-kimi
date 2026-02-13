using System.Net;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Metadata;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Retry;

namespace Gabi.Fetch;

/// <summary>
/// Service for fetching metadata and content from URLs with retry policy
/// </summary>
public class FetchService : IFetchService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<FetchService>? _logger;
    private readonly AsyncRetryPolicy<HttpResponseMessage> _retryPolicy;
    private readonly IMetadataExtractor _metadataExtractor;

    public FetchService(HttpClient httpClient, ILogger<FetchService>? logger = null)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _logger = logger;
        _metadataExtractor = new MetadataExtractor(httpClient);
        _retryPolicy = CreateRetryPolicy();
    }

    /// <inheritdoc />
    public async Task<ResourceMetadata> FetchMetadataAsync(string url, CancellationToken ct = default)
    {
        return await _metadataExtractor.ExtractMetadataAsync(url, ct);
    }

    /// <inheritdoc />
    public async Task<FetchResult> FetchAsync(string url, FetchOptions options, CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);
        ArgumentNullException.ThrowIfNull(options);

        // First, fetch metadata to check size
        var metadata = await FetchMetadataAsync(url, ct);

        // Check if metadata fetch failed
        if (!string.IsNullOrEmpty(metadata.ErrorMessage))
        {
            return new FetchResult
            {
                Success = false,
                ErrorMessage = metadata.ErrorMessage,
                Metadata = metadata
            };
        }

        // Check size limit
        if (options.MaxSizeBytes.HasValue && 
            metadata.ContentLength.HasValue && 
            metadata.ContentLength.Value > options.MaxSizeBytes.Value)
        {
            var errorMsg = $"Content size ({metadata.ContentLength.Value} bytes) exceeds maximum allowed ({options.MaxSizeBytes.Value} bytes)";
            _logger?.LogWarning(errorMsg);
            
            return new FetchResult
            {
                Success = false,
                ErrorMessage = errorMsg,
                Metadata = metadata
            };
        }

        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(options.Timeout);

            byte[]? content = null;

            if (options.UseStreaming)
            {
                content = await FetchWithStreamingAsync(url, options, cts.Token);
            }
            else
            {
                content = await FetchWithoutStreamingAsync(url, cts.Token);
            }

            return new FetchResult
            {
                Success = true,
                Content = content,
                Metadata = metadata
            };
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            var errorMsg = $"Request timed out after {options.Timeout}";
            _logger?.LogWarning(errorMsg);
            
            return new FetchResult
            {
                Success = false,
                ErrorMessage = errorMsg,
                Metadata = metadata
            };
        }
        catch (Exception ex)
        {
            _logger?.LogError(ex, "Failed to fetch content from {Url}", url);
            
            return new FetchResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                Metadata = metadata
            };
        }
    }

    private AsyncRetryPolicy<HttpResponseMessage> CreateRetryPolicy()
    {
        return Policy
            .Handle<HttpRequestException>()
            .OrResult<HttpResponseMessage>(r => 
                (int)r.StatusCode >= 500 || // Server errors
                r.StatusCode == HttpStatusCode.RequestTimeout || // 408
                r.StatusCode == HttpStatusCode.TooManyRequests) // 429
            .WaitAndRetryAsync(
                retryCount: 3,
                sleepDurationProvider: retryAttempt => 
                    TimeSpan.FromSeconds(Math.Pow(2, retryAttempt)), // Exponential backoff: 2, 4, 8 seconds
                onRetry: (outcome, timespan, retryCount, context) =>
                {
                    var statusCode = outcome.Result?.StatusCode.ToString() ?? "Exception";
                    _logger?.LogWarning(
                        "Retry {RetryCount} after {Delay}s due to {StatusCode}",
                        retryCount, timespan.TotalSeconds, statusCode);
                });
    }

    private async Task<byte[]> FetchWithoutStreamingAsync(string url, CancellationToken ct)
    {
        var response = await _retryPolicy.ExecuteAsync(async token =>
        {
            var response = await _httpClient.GetAsync(url, token);
            return response;
        }, ct);

        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsByteArrayAsync(ct);
    }

    private async Task<byte[]> FetchWithStreamingAsync(string url, FetchOptions options, CancellationToken ct)
    {
        var response = await _retryPolicy.ExecuteAsync(async token =>
        {
            var request = new HttpRequestMessage(HttpMethod.Get, url);
            var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
            return response;
        }, ct);

        response.EnsureSuccessStatusCode();

        // If we don't know the content length, we need to limit the read
        if (!response.Content.Headers.ContentLength.HasValue && options.MaxSizeBytes.HasValue)
        {
            return await ReadWithSizeLimitAsync(response, options.MaxSizeBytes.Value, ct);
        }

        return await response.Content.ReadAsByteArrayAsync(ct);
    }

    private static async Task<byte[]> ReadWithSizeLimitAsync(
        HttpResponseMessage response, long maxSizeBytes, CancellationToken ct)
    {
        using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var ms = new MemoryStream();
        var buffer = new byte[8192];
        long totalRead = 0;

        while (true)
        {
            var read = await stream.ReadAsync(buffer, 0, buffer.Length, ct);
            if (read == 0) break;

            totalRead += read;
            if (totalRead > maxSizeBytes)
            {
                throw new InvalidOperationException(
                    $"Content exceeds maximum size limit of {maxSizeBytes} bytes");
            }

            await ms.WriteAsync(buffer, 0, read, ct);
        }

        return ms.ToArray();
    }
}
