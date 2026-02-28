namespace Gabi.ZeroKelvinHarness.Pipeline;

/// <summary>
/// Seeds controlled dataset sizes: generates synthetic sources YAML or points to repo sources_v2.yaml with cap.
/// </summary>
public sealed class DatasetSeeder
{
    /// <summary>
    /// Returns the path to a synthetic sources YAML with N static_url sources (each one URL). Caller can set GABI_SOURCES_PATH to this.
    /// </summary>
    public static string CreateSyntheticSourcesYaml(int sourceCount, string tempDir)
    {
        Directory.CreateDirectory(tempDir);
        var path = Path.Combine(tempDir, $"sources_synthetic_{Guid.NewGuid():N}.yaml");
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("defaults:");
        sb.AppendLine("  pipeline:");
        sb.AppendLine("    coverage:");
        sb.AppendLine("      strict: false");
        sb.AppendLine("sources:");
        for (var i = 0; i < sourceCount; i++)
        {
            var id = $"harness_source_{i}";
            sb.AppendLine($"  {id}:");
            sb.AppendLine("    name: Harness Source " + i);
            sb.AppendLine("    provider: static");
            sb.AppendLine("    discovery:");
            sb.AppendLine("      strategy: static_url");
            sb.AppendLine("      config:");
            sb.AppendLine("        url: https://example.com/doc-" + i);
        }
        File.WriteAllText(path, sb.ToString());
        return path;
    }

    /// <summary>
    /// Returns expected document count for the synthetic dataset (one doc per static_url source).
    /// </summary>
    public static int GetExpectedDocumentCountSynthetic(int sourceCount) => sourceCount;

    /// <summary>
    /// Returns the path to the repository sources_v2.yaml if it exists; otherwise null.
    /// </summary>
    public static string? GetRepoSourcesPath(string repoRoot)
    {
        var path = Path.Combine(repoRoot, "sources_v2.yaml");
        return File.Exists(path) ? Path.GetFullPath(path) : null;
    }
}
