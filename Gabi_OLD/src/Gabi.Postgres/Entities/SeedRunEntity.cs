using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro de uma execução do seed (carregamento do sources_v2.yaml no banco).
/// Alimenta a próxima fase (discovery): frontend/API podem consultar a última seed para saber se o catálogo está pronto.
/// </summary>
[Table("seed_runs")]
public class SeedRunEntity : RunAuditBase
{
    public int SourcesTotal { get; set; }
    public int SourcesSeeded { get; set; }
    public int SourcesFailed { get; set; }
}
