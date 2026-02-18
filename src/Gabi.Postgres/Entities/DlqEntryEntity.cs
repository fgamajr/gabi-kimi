using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Dead Letter Queue entry for jobs that failed after max retries.
/// Allows inspection, replay, and alerting on permanently failed jobs.
/// </summary>
[Table("dlq_entries")]
public class DlqEntryEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? SourceId { get; set; }

    public Guid? OriginalJobId { get; set; }

    [MaxLength(100)]
    public string? HangfireJobId { get; set; }

    [Column(TypeName = "jsonb")]
    public string? Payload { get; set; }

    [MaxLength(4000)]
    public string? ErrorMessage { get; set; }

    [MaxLength(200)]
    public string? ErrorType { get; set; }

    [Column(TypeName = "jsonb")]
    public string? StackTrace { get; set; }

    public int RetryCount { get; set; }

    public DateTime FailedAt { get; set; } = DateTime.UtcNow;

    public DateTime? ReplayedAt { get; set; }

    [MaxLength(100)]
    public string? ReplayedBy { get; set; }

    public Guid? ReplayedAsJobId { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    [MaxLength(500)]
    public string? Notes { get; set; }
}
