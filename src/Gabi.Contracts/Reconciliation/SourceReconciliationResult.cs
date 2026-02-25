namespace Gabi.Contracts.Reconciliation;

/// <summary>
/// Result of reconciling PG active document count vs index active count for a source (CODEX-D).
/// </summary>
public record SourceReconciliationResult
{
    public int PgActiveCount { get; init; }
    public int IndexActiveCount { get; init; }
    /// <summary>|Pg - Index| / Max(Pg, 1).</summary>
    public double DriftRatio { get; init; }
}
