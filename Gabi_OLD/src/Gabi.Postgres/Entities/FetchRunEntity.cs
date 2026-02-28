using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução de fetch para uma fonte.
/// </summary>
[Table("fetch_runs")]
public class FetchRunEntity : RunAuditBase
{
    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    public int ItemsTotal { get; set; }
    public int ItemsCompleted { get; set; }
    public int ItemsFailed { get; set; }
}
