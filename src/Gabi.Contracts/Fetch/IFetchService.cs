using Gabi.Contracts.Metadata;

namespace Gabi.Contracts.Fetch;

/// <summary>
/// Service for fetching metadata and content from URLs
/// </summary>
public interface IFetchService
{
    /// <summary>
    /// Fetches only metadata (HEAD request)
    /// </summary>
    /// <param name="url">URL to fetch metadata from</param>
    /// <param name="ct">Cancellation token</param>
    /// <returns>Resource metadata</returns>
    Task<ResourceMetadata> FetchMetadataAsync(string url, CancellationToken ct = default);
    
    /// <summary>
    /// Full fetch - downloads content (for Phase 1)
    /// </summary>
    /// <param name="url">URL to fetch content from</param>
    /// <param name="options">Fetch options</param>
    /// <param name="ct">Cancellation token</param>
    /// <returns>Fetch result with content and metadata</returns>
    Task<FetchResult> FetchAsync(string url, FetchOptions options, CancellationToken ct = default);
}

/// <summary>
/// Options for fetch operations
/// </summary>
public record FetchOptions
{
    /// <summary>Maximum size in bytes (default 100MB)</summary>
    public long? MaxSizeBytes { get; init; } = 100 * 1024 * 1024;
    
    /// <summary>Timeout for the request (default 5 minutes)</summary>
    public TimeSpan Timeout { get; init; } = TimeSpan.FromMinutes(5);
    
    /// <summary>Use streaming for large files</summary>
    public bool UseStreaming { get; init; } = true;
}

/// <summary>
/// Result of a fetch operation
/// </summary>
public record FetchResult
{
    /// <summary>True if fetch was successful</summary>
    public bool Success { get; init; }
    
    /// <summary>Error message if fetch failed</summary>
    public string? ErrorMessage { get; init; }
    
    /// <summary>Downloaded content (null if failed or streaming)</summary>
    public byte[]? Content { get; init; }
    
    /// <summary>Resource metadata from HEAD request</summary>
    public ResourceMetadata Metadata { get; init; } = null!;
}
