using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Execution state of a source pipeline (idle, running, paused, failed).
/// Used for Pause/Resume/Stop and graceful interruption of long-running jobs.
/// </summary>
[Table("source_pipeline_state")]
public class SourcePipelineStateEntity
{
    [Key]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    /// <summary>idle, running, paused, failed</summary>
    [Required]
    [MaxLength(20)]
    public string State { get; set; } = "idle";

    /// <summary>discovery, fetch, ingest, embed</summary>
    [MaxLength(20)]
    public string? ActivePhase { get; set; }

    [MaxLength(100)]
    public string? PausedBy { get; set; }

    public DateTime? PausedAt { get; set; }

    public DateTime? LastResumedAt { get; set; }

    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
