using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução do seed (carregamento do sources_v2.yaml no banco).
/// Alimenta a próxima fase (discovery): frontend/API podem consultar a última seed para saber se o catálogo está pronto.
/// </summary>
[Table("seed_runs")]
public class SeedRunEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>Job ID do ingest_jobs que executou este seed.</summary>
    public Guid JobId { get; set; }

    public DateTime StartedAt { get; set; }
    public DateTime CompletedAt { get; set; }

    public int SourcesTotal { get; set; }
    public int SourcesSeeded { get; set; }
    public int SourcesFailed { get; set; }

    /// <summary>completed | partial | failed</summary>
    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "completed";

    /// <summary>Resumo de erros (ex.: IDs que falharam após retries).</summary>
    [MaxLength(2000)]
    public string? ErrorSummary { get; set; }
}
