namespace Gabi.Contracts.Metadata;

/// <summary>
/// Interface for extracting and comparing resource metadata via HEAD requests
/// </summary>
public interface IMetadataExtractor
{
    /// <summary>
    /// Fetches metadata via HEAD request without downloading content
    /// </summary>
    /// <param name="url">URL to fetch metadata from</param>
    /// <param name="ct">Cancellation token</param>
    /// <returns>Resource metadata</returns>
    Task<ResourceMetadata> ExtractMetadataAsync(string url, CancellationToken ct = default);
    
    /// <summary>
    /// Compares new metadata with cached/stored metadata
    /// </summary>
    /// <param name="current">Current metadata from HEAD request</param>
    /// <param name="previous">Previous/stored metadata (null for new resources)</param>
    /// <returns>Comparison result indicating if resource changed</returns>
    Task<MetadataComparisonResult> CompareAsync(ResourceMetadata current, ResourceMetadata? previous);
    
    /// <summary>
    /// Estimates document count from resource metadata
    /// For CSV: uses average row size heuristic
    /// </summary>
    /// <param name="metadata">Resource metadata</param>
    /// <param name="fileType">File type hint (csv, json, xml, etc.)</param>
    /// <returns>Estimated document count or null if cannot estimate</returns>
    int? EstimateDocumentCount(ResourceMetadata metadata, string fileType);
}
