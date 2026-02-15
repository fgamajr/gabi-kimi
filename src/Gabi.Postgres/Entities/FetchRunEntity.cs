using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução de fetch para uma fonte.
/// </summary>
[Table("fetch_runs")]
public class FetchRunEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid JobId { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    public DateTime StartedAt { get; set; }
    public DateTime CompletedAt { get; set; }

    public int ItemsTotal { get; set; }
    public int ItemsCompleted { get; set; }
    public int ItemsFailed { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "completed";

    [MaxLength(2000)]
    public string? ErrorSummary { get; set; }
}

