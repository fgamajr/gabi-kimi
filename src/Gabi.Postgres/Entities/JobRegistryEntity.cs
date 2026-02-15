using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Registro leve de jobs para o dashboard (GetLatest*, GetRecentJobs, GetStatistics).
/// Hangfire guarda o estado real da fila; esta tabela permite consultas por source/tipo sem depender do IMonitoringApi.
/// </summary>
[Table("job_registry")]
public class JobRegistryEntity
{
    [Key]
    public Guid JobId { get; set; }

    [MaxLength(100)]
    public string? HangfireJobId { get; set; }

    [MaxLength(100)]
    public string? SourceId { get; set; }

    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = "sync";

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }

    [MaxLength(2000)]
    public string? ErrorMessage { get; set; }

    public int ProgressPercent { get; set; }
    [MaxLength(500)]
    public string? ProgressMessage { get; set; }
}
