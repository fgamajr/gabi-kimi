namespace Gabi.ZeroKelvinHarness.Models;

/// <summary>
/// Document/item count for a pipeline stage. Used by StageTracker.
/// </summary>
public sealed record StageCount
{
    public string Stage { get; init; } = string.Empty;
    public int Count { get; init; }
    public string? StatusFilter { get; init; }
}
