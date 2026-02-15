using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução de discovery para uma fonte.
/// Alimenta a próxima fase (fetch): frontend/API podem consultar o último run por source.
/// </summary>
[Table("discovery_runs")]
public class DiscoveryRunEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>Job ID do ingest_jobs que executou este discovery.</summary>
    public Guid JobId { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    public DateTime StartedAt { get; set; }
    public DateTime CompletedAt { get; set; }

    public int LinksTotal { get; set; }

    /// <summary>completed | partial | failed</summary>
    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "completed";

    /// <summary>Resumo de erros (ex.: mensagem de exceção após retries).</summary>
    [MaxLength(2000)]
    public string? ErrorSummary { get; set; }
}
