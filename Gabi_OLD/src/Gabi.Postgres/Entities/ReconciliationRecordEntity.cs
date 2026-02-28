using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Record of PG vs index reconciliation at end of an ingest run (CODEX-D).
/// </summary>
[Table("reconciliation_records")]
public class ReconciliationRecordEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>Ingest job/run this record belongs to.</summary>
    public Guid RunId { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    public int PgActiveCount { get; set; }
    public int IndexActiveCount { get; set; }
    public double DriftRatio { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "ok"; // ok | drifted | error

    public DateTime ReconciledAt { get; set; }
}
