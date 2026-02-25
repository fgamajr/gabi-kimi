using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Comparison;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

/// <summary>
/// Expands URL patterns with year ranges into individual discovered links.
/// </summary>
public class UrlPatternExpander
{
    /// <summary>
    /// Expands a URL pattern configuration into a list of discovered links.
    /// </summary>
    /// <param name="config">URL pattern config with template and year range.</param>
    /// <param name="sourceId">Source identifier.</param>
    /// <param name="snapshotYear">Year to use for "current" when resolving end of range; null uses DateTime.UtcNow.Year.</param>
    public IReadOnlyList<DiscoveredLink> Expand(UrlPatternConfig config, string sourceId, int? snapshotYear = null)
    {
        if (config == null)
            throw new ArgumentNullException(nameof(config));

        if (string.IsNullOrEmpty(config.Template))
            throw new ArgumentException("Template cannot be empty", nameof(config));

        if (config.YearRange == null)
            throw new ArgumentException("YearRange is required for URL pattern expansion", nameof(config));

        var links = new List<DiscoveredLink>();
        var yearRange = config.YearRange;
        var end = yearRange.ResolveEnd(snapshotYear);
        
        for (var year = yearRange.Start; year <= end; year += yearRange.Step)
        {
            var url = config.Template.Replace("{year}", year.ToString());
            var urlHash = ComputeSha256Hash(url);
            
            links.Add(new DiscoveredLink
            {
                SourceId = sourceId,
                Url = url,
                UrlHash = urlHash,
                DocumentCount = null, // Unknown until fetch
                TotalSizeBytes = null,
                Metadata = new Dictionary<string, object>(),
                DiscoveredAt = DateTime.UtcNow
            });
        }
        
        return links;
    }

    /// <summary>
    /// Computes SHA256 hash of a string.
    /// </summary>
    private static string ComputeSha256Hash(string input)
    {
        using var sha256 = SHA256.Create();
        var bytes = Encoding.UTF8.GetBytes(input);
        var hash = sha256.ComputeHash(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
