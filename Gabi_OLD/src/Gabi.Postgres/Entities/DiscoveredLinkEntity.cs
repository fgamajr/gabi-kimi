using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Status of a discovered link in the processing pipeline.
/// </summary>
public enum LinkStatus
{
    Pending,      // Waiting to be processed
    Queued,       // In job queue
    Processing,   // Currently being processed
    Completed,    // Successfully processed
    Failed,       // Failed, may retry
    Skipped,      // Skipped (duplicate, filtered, etc.)
    Stale         // No longer present in source
}

/// <summary>
/// A URL discovered during source refresh.
/// </summary>
[Table("discovered_links")]
[Index(nameof(SourceId), nameof(Status))]
[Index(nameof(ContentHash))]
[Index(nameof(DiscoveredAt))]
public class DiscoveredLinkEntity : AuditableEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    [ForeignKey(nameof(SourceId))]
    public SourceRegistryEntity Source { get; set; } = null!;

    [Required]
    public string Url { get; set; } = string.Empty;

    /// <summary>
    /// SHA256 hash of URL for unique constraint.
    /// </summary>
    [Required]
    [MaxLength(64)]
    public string UrlHash { get; set; } = string.Empty;

    /// <summary>
    /// When this link was first discovered (immutable).
    /// </summary>
    public DateTime FirstSeenAt { get; set; } = DateTime.UtcNow;

    /// <summary>
    /// When this link was discovered (may be updated on re-discovery).
    /// </summary>
    public DateTime DiscoveredAt { get; set; } = DateTime.UtcNow;

    [MaxLength(255)]
    public string? Etag { get; set; }

    public DateTime? LastModified { get; set; }

    public long? ContentLength { get; set; }

    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    /// <summary>Status na fase discovery: completed quando o link foi descoberto e persistido.</summary>
    [MaxLength(20)]
    public string DiscoveryStatus { get; set; } = "completed";

    /// <summary>Status na fase fetch: pending até o fetch processar este link.</summary>
    [MaxLength(20)]
    public string FetchStatus { get; set; } = "pending";

    /// <summary>Status na fase ingest: pending até o ingest processar.</summary>
    [MaxLength(20)]
    public string IngestStatus { get; set; } = "pending";

    public DateTime? LastProcessedAt { get; set; }

    public int ProcessAttempts { get; set; }

    public int MaxAttempts { get; set; } = 3;

    [MaxLength(64)]
    public string? ContentHash { get; set; }

    [MaxLength(64)]
    public string? LastContentHash { get; set; }

    /// <summary>
    /// Number of documents in this link (if known).
    /// </summary>
    public int? DocumentCount { get; set; }

    /// <summary>
    /// Total size in bytes (if known).
    /// </summary>
    public long? TotalSizeBytes { get; set; }

    /// <summary>
    /// Hash of metadata for change detection.
    /// </summary>
    [MaxLength(64)]
    public string? MetadataHash { get; set; }

    /// <summary>
    /// Flexible metadata stored as JSONB.
    /// </summary>
    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";

    // Navigation
    public ICollection<IngestJobEntity> Jobs { get; set; } = new List<IngestJobEntity>();
    public ICollection<FetchItemEntity> FetchItems { get; set; } = new List<FetchItemEntity>();
    
    /// <summary>
    /// Documents extracted from this link.
    /// </summary>
    public ICollection<DocumentEntity> Documents { get; set; } = new List<DocumentEntity>();
}
