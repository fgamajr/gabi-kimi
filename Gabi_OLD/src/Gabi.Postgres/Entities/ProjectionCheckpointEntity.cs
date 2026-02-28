using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Persists the WAL LSN for the projection worker so it can resume after restart.
/// </summary>
[Table("projection_checkpoint")]
public class ProjectionCheckpointEntity
{
    [Key]
    [MaxLength(100)]
    public string SlotName { get; set; } = string.Empty;

    /// <summary>PostgreSQL LSN stored as text (e.g. "0/1A2B3C4D"). Parsed at read time.</summary>
    [Required]
    public string Lsn { get; set; } = "0/0";

    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
