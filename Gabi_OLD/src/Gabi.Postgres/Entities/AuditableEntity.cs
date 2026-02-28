using System.ComponentModel.DataAnnotations;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Base entity with audit and concurrency support.
/// </summary>
public abstract class AuditableEntity
{
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    public string CreatedBy { get; set; } = "system";
    public string UpdatedBy { get; set; } = "system";

    /// <summary>
    /// Optimistic concurrency token (PostgreSQL xmin).
    /// </summary>
    [Timestamp]
    public uint Version { get; set; }
}
