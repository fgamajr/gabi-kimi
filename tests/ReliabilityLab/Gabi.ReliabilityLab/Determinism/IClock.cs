namespace Gabi.ReliabilityLab.Determinism;

public interface IClock
{
    DateTimeOffset UtcNow { get; }
}
