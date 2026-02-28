namespace Gabi.Contracts.Metadata;

/// <summary>
/// Resource metadata - what we learn from HEAD request
/// </summary>
public record ResourceMetadata
{
    /// <summary>URL of the resource</summary>
    public string Url { get; init; } = null!;
    
    /// <summary>Content-Length from headers (if available)</summary>
    public long? ContentLength { get; init; }
    
    /// <summary>Content-Type from headers</summary>
    public string? ContentType { get; init; }
    
    /// <summary>ETag for change detection</summary>
    public string? ETag { get; init; }
    
    /// <summary>Last-Modified date from headers</summary>
    public DateTime? LastModified { get; init; }
    
    /// <summary>Filename parsed from URL or Content-Disposition</summary>
    public string? Filename { get; init; }
    
    /// <summary>Estimated document count from size/heuristics</summary>
    public int? EstimatedDocumentCount { get; init; }
    
    /// <summary>HTTP Status code from HEAD request</summary>
    public int? StatusCode { get; init; }
    
    /// <summary>Error message if HEAD request failed</summary>
    public string? ErrorMessage { get; init; }
}

/// <summary>
/// Result of comparing two metadata snapshots
/// </summary>
public record MetadataComparisonResult
{
    /// <summary>True if resource has changed</summary>
    public bool HasChanged { get; init; }
    
    /// <summary>Reason for change: "size_changed", "etag_changed", "lastmodified_changed", "new_resource"</summary>
    public string? ChangeReason { get; init; }
    
    /// <summary>Previous metadata (null if new resource)</summary>
    public ResourceMetadata? PreviousMetadata { get; init; }
    
    /// <summary>Current metadata</summary>
    public ResourceMetadata CurrentMetadata { get; init; } = null!;
}
