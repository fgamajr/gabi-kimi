using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Audit record of a source refresh operation.
/// </summary>
[Table("source_refresh")]
[Index(nameof(SourceId), nameof(StartedAt))]
[Index(nameof(Status), nameof(HeartbeatAt))]
public class SourceRefreshEntity : AuditableEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    [ForeignKey(nameof(SourceId))]
    public SourceRegistryEntity Source { get; set; } = null!;

    public DateTime StartedAt { get; set; } = DateTime.UtcNow;

    public DateTime? CompletedAt { get; set; }

    [MaxLength(20)]
    public string Status { get; set; } = "running";

    public int LinksDiscovered { get; set; }

    public int LinksNew { get; set; }

    public int LinksUpdated { get; set; }

    public int LinksRemoved { get; set; }

    public string? ErrorMessage { get; set; }

    [Column(TypeName = "jsonb")]
    public string? ErrorDetails { get; set; }

    public int? DurationMs { get; set; }

    public int? PeakMemoryMb { get; set; }

    [MaxLength(100)]
    public string TriggeredBy { get; set; } = "system";

    [MaxLength(100)]
    public string? RequestId { get; set; }

    [MaxLength(100)]
    public string? WorkerId { get; set; }

    public DateTime? HeartbeatAt { get; set; }
}
