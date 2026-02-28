namespace Gabi.ReliabilityLab.Determinism;

/// <summary>
/// Seeded RNG for reproducible sampling and shuffling. Same seed → same sequence.
/// </summary>
public sealed class DeterministicRandom
{
    private readonly Random _rng;

    public int Seed { get; }

    public DeterministicRandom(int seed)
    {
        Seed = seed;
        _rng = new Random(seed);
    }

    public int Next(int maxExclusive) => _rng.Next(maxExclusive);

    public double NextDouble() => _rng.NextDouble();

    /// <summary>Fisher-Yates shuffle. Mutates the array in place.</summary>
    public void Shuffle<T>(T[] items)
    {
        for (var i = items.Length - 1; i > 0; i--)
        {
            var j = _rng.Next(i + 1);
            (items[i], items[j]) = (items[j], items[i]);
        }
    }

    /// <summary>Returns a new array with up to count elements sampled without replacement.</summary>
    public T[] Sample<T>(IReadOnlyList<T> items, int count)
    {
        if (items.Count == 0 || count <= 0) return Array.Empty<T>();
        var n = Math.Min(count, items.Count);
        var indices = Enumerable.Range(0, items.Count).ToArray();
        Shuffle(indices);
        var result = new T[n];
        for (var i = 0; i < n; i++)
            result[i] = items[indices[i]];
        return result;
    }
}
