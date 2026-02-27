using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// WAL projection DLQ — receives failed WAL events for manual replay.
/// NOT a projection outbox feed; only written on failure.
/// </summary>
[Table("projection_dlq")]
public class ProjectionDlqEntity
{
    [Key]
    [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
    public long Id { get; set; }

    [Required]
    [MaxLength(255)]
    public string DocumentId { get; set; } = string.Empty;

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    /// <summary>upsert | delete</summary>
    [Required]
    [MaxLength(20)]
    public string Operation { get; set; } = string.Empty;

    [Required]
    [Column(TypeName = "jsonb")]
    public string Payload { get; set; } = "{}";

    public string? Error { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public DateTime? ReplayedAt { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "pending";
}
