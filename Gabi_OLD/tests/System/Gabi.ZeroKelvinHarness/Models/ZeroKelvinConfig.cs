namespace Gabi.ZeroKelvinHarness.Models;

/// <summary>
/// Configuration for a Zero-Kelvin experiment run.
/// </summary>
public sealed record ZeroKelvinConfig
{
    /// <summary>Maximum documents to process per source (cap).</summary>
    public int MaxDocs { get; init; } = 1000;

    /// <summary>Source ID to run (e.g. single source). If null, uses dataset seeder default.</summary>
    public string? SourceId { get; init; }

    /// <summary>Phases to run: seed, discovery, fetch, ingest. Default is full pipeline.</summary>
    public IReadOnlyList<string> Phases { get; init; } = new[] { "seed", "discovery", "fetch", "ingest" };

    /// <summary>Sample size for document verification.</summary>
    public int SampleSize { get; init; } = 50;

    /// <summary>Timeout per phase (e.g. discovery, fetch).</summary>
    public TimeSpan PhaseTimeout { get; init; } = TimeSpan.FromMinutes(5);

    /// <summary>Path to sources YAML. If null, uses synthetic dataset from DatasetSeeder.</summary>
    public string? SourcesYamlPath { get; init; }
}
