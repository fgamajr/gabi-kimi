namespace Gabi.ReliabilityLab.Determinism;

/// <summary>
/// Deterministic clock for unit tests. Time can be advanced explicitly.
/// </summary>
public sealed class FixedClock : IClock
{
    private DateTimeOffset _now;

    public FixedClock(DateTimeOffset fixedTime) => _now = fixedTime;

    public DateTimeOffset UtcNow => _now;

    public void Advance(TimeSpan delta) => _now = _now.Add(delta);
}
