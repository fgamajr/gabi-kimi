using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução de discovery para uma fonte.
/// Alimenta a próxima fase (fetch): frontend/API podem consultar o último run por source.
/// </summary>
[Table("discovery_runs")]
public class DiscoveryRunEntity : RunAuditBase
{
    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    public int LinksTotal { get; set; }
}
