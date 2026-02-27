using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Append-only stage history event (best-effort observability).
/// </summary>
[Table("workflow_events")]
public class WorkflowEventEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid CorrelationId { get; set; }

    public Guid JobId { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = string.Empty;

    /// <summary>stage_started | stage_completed | stage_failed</summary>
    [Required]
    [MaxLength(50)]
    public string EventType { get; set; } = string.Empty;

    [Column(TypeName = "jsonb")]
    public string? Metadata { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
