using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// A document extracted from a discovered link (future ingest phase).
/// </summary>
[Table("documents")]
[Index(nameof(LinkId))]
[Index(nameof(Status))]
[Index(nameof(CreatedAt))]
public class DocumentEntity : AuditableEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    public long LinkId { get; set; }

    [ForeignKey(nameof(LinkId))]
    public DiscoveredLinkEntity Link { get; set; } = null!;

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    /// <summary>
    /// Document identifier (e.g., process number, ID from source).
    /// </summary>
    [MaxLength(255)]
    public string? DocumentId { get; set; }

    /// <summary>
    /// Document title or summary.
    /// </summary>
    public string? Title { get; set; }

    /// <summary>
    /// Document content (may be stored externally in S3/minio for large docs).
    /// </summary>
    public string? Content { get; set; }

    /// <summary>
    /// URL to external storage if content is not inline.
    /// </summary>
    [MaxLength(2048)]
    public string? ContentUrl { get; set; }

    /// <summary>
    /// Content hash for deduplication.
    /// </summary>
    [MaxLength(64)]
    public string? ContentHash { get; set; }

    [MaxLength(20)]
    public string Status { get; set; } = "pending"; // pending, processing, completed, failed

    /// <summary>
    /// Processing stage (chunking, embedding, indexing).
    /// </summary>
    [MaxLength(50)]
    public string? ProcessingStage { get; set; }

    public DateTime? ProcessingStartedAt { get; set; }
    public DateTime? ProcessingCompletedAt { get; set; }

    /// <summary>
    /// JSONB metadata (source-specific fields).
    /// </summary>
    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";

    /// <summary>
    /// Vector embedding ID in vector store (future).
    /// </summary>
    public Guid? EmbeddingId { get; set; }

    /// <summary>
    /// Elasticsearch document ID (future).
    /// </summary>
    [MaxLength(255)]
    public string? ElasticsearchId { get; set; }
}
