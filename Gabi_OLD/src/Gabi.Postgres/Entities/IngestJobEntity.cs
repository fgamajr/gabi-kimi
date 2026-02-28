using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// A job in the ingest queue.
/// </summary>
[Table("ingest_jobs")]
[Index(nameof(Status), nameof(Priority), nameof(ScheduledAt), nameof(CreatedAt), Name = "idx_jobs_available")]
[Index(nameof(Status), nameof(WorkerId), nameof(LockedAt))]
[Index(nameof(LinkId))]
[Index(nameof(SourceId))]
public class IngestJobEntity : AuditableEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = string.Empty;

    [Required]
    [Column(TypeName = "jsonb")]
    public string Payload { get; set; } = "{}";

    [Required]
    [MaxLength(64)]
    public string PayloadHash { get; set; } = string.Empty;

    public long? LinkId { get; set; }

    [ForeignKey(nameof(LinkId))]
    public DiscoveredLinkEntity? Link { get; set; }

    public long? FetchItemId { get; set; }

    [ForeignKey(nameof(FetchItemId))]
    public FetchItemEntity? FetchItem { get; set; }

    [MaxLength(100)]
    public string? SourceId { get; set; }

    [ForeignKey(nameof(SourceId))]
    public SourceRegistryEntity? Source { get; set; }

    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    public int Priority { get; set; } = 2; // Normal = 2

    public DateTime ScheduledAt { get; set; } = DateTime.UtcNow;

    public DateTime? StartedAt { get; set; }

    public DateTime? CompletedAt { get; set; }

    public int Attempts { get; set; }

    public int MaxAttempts { get; set; } = 3;

    public string? LastError { get; set; }

    [Column(TypeName = "jsonb")]
    public string? ErrorDetails { get; set; }

    public DateTime? RetryAt { get; set; }

    [MaxLength(100)]
    public string? WorkerId { get; set; }

    public DateTime? LockedAt { get; set; }

    public DateTime? LockExpiresAt { get; set; }

    public int? ProgressPercent { get; set; }

    public string? ProgressMessage { get; set; }

    public int LinksDiscovered { get; set; }

    [Column(TypeName = "jsonb")]
    public string? Result { get; set; }
}
