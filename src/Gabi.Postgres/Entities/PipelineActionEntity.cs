using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Auditoria de ações operacionais do pipeline (manual resume, restart, etc.).
/// </summary>
[Table("pipeline_actions")]
public class PipelineActionEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    [MaxLength(50)]
    public string Action { get; set; } = string.Empty;

    [Required]
    [MaxLength(30)]
    public string Scope { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? SourceId { get; set; }

    [Column(TypeName = "jsonb")]
    public string Params { get; set; } = "{}";

    [MaxLength(100)]
    public string Actor { get; set; } = "system";

    public DateTime At { get; set; } = DateTime.UtcNow;
}

