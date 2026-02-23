using System.ComponentModel.DataAnnotations;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Common audit fields for run entities.
/// </summary>
public abstract class RunAuditBase
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid JobId { get; set; }

    public DateTime StartedAt { get; set; }
    public DateTime CompletedAt { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "completed";

    [MaxLength(2000)]
    public string? ErrorSummary { get; set; }
}
