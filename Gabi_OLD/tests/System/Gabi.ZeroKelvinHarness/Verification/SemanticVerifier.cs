using System.Globalization;
using System.Text.RegularExpressions;

namespace Gabi.ZeroKelvinHarness.Verification;

/// <summary>
/// Normalized text comparison and token similarity heuristic. Classifies preserved / degraded / corrupted.
/// </summary>
public static class SemanticVerifier
{
    private static readonly Regex WordRegex = new(@"\b\w+\b", RegexOptions.Compiled);

    /// <summary>
    /// Normalizes text: lowercase, collapse whitespace, trim.
    /// </summary>
    public static string Normalize(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return string.Empty;
        var normalized = text.Trim().ToLowerInvariant();
        normalized = Regex.Replace(normalized, @"\s+", " ");
        return normalized;
    }

    /// <summary>
    /// Token-level Jaccard similarity: |A ∩ B| / |A ∪ B| using word tokens.
    /// </summary>
    public static double TokenJaccard(string? original, string? stored)
    {
        var a = WordRegex.Matches(Normalize(original)).Select(m => m.Value).ToHashSet();
        var b = WordRegex.Matches(Normalize(stored)).Select(m => m.Value).ToHashSet();
        if (a.Count == 0 && b.Count == 0) return 1.0;
        if (a.Count == 0 || b.Count == 0) return 0.0;
        var inter = a.Intersect(b).Count();
        var union = a.Union(b).Count();
        return union == 0 ? 1.0 : (double)inter / union;
    }

    /// <summary>
    /// Classifies similarity score: preserved (&gt;0.95), degraded (0.7–0.95), corrupted (&lt;0.7).
    /// </summary>
    public static string Classify(double similarity)
    {
        if (similarity > 0.95) return "preserved";
        if (similarity >= 0.7) return "degraded";
        return "corrupted";
    }

    /// <summary>
    /// Computes average semantic preservation score from a list of (original, stored) pairs.
    /// When original is not available (e.g. not stored in DB), pass stored for both to get 1.0 per document.
    /// </summary>
    public static double SemanticPreservationScore(IEnumerable<(string? Original, string? Stored)> pairs)
    {
        var list = pairs.ToList();
        if (list.Count == 0) return 1.0;
        var sum = 0.0;
        foreach (var (orig, stored) in list)
            sum += TokenJaccard(orig, stored);
        return sum / list.Count;
    }
}
