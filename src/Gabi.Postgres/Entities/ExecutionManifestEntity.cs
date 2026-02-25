using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Manifest of a discovery run: snapshot time, resolved parameters, link counts and external_id_set_hash
/// for reproducibility and strict coverage checks.
/// </summary>
[Table("execution_manifest")]
public class ExecutionManifestEntity
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    /// <summary>Discovery run this manifest belongs to.</summary>
    public Guid DiscoveryRunId { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    /// <summary>Snapshot time frozen at run start (e.g. for "current" year).</summary>
    public DateTime SnapshotAt { get; set; }

    /// <summary>Resolved parameters (e.g. year range) as JSON.</summary>
    [Column(TypeName = "jsonb")]
    public string? ResolvedParameters { get; set; }

    public int? ExpectedLinkCount { get; set; }
    public int ActualLinkCount { get; set; }
    public int? ActualFetchCount { get; set; }
    public int? ActualIngestCount { get; set; }

    /// <summary>SHA-256 hex of sorted external_ids (or URLs) discovered in this run.</summary>
    [Required]
    [MaxLength(64)]
    public string ExternalIdSetHash { get; set; } = string.Empty;

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "completed";

    /// <summary>actual_link_count / expected_link_count when expected is set.</summary>
    public decimal? CoverageRatio { get; set; }
}
