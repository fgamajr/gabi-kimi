using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Comparison;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

/// <summary>
/// V2 Discovery Engine that uses the new SourceDefinition contracts.
/// </summary>
public class DiscoveryEngineV2
{
    private readonly UrlPatternExpander _expander = new();

    /// <summary>
    /// Discovers links for a given source definition.
    /// </summary>
    public Task<DiscoveryResult> DiscoverAsync(SourceDefinition sourceDefinition, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();

        var links = sourceDefinition.Discovery.StrategyEnum switch
        {
            DiscoveryStrategy.StaticUrl => DiscoverStaticUrl(sourceDefinition),
            DiscoveryStrategy.UrlPattern => DiscoverUrlPattern(sourceDefinition),
            DiscoveryStrategy.WebCrawl => throw new NotSupportedException("Web crawl strategy not yet implemented"),
            DiscoveryStrategy.ApiPagination => throw new NotSupportedException("API pagination strategy not yet implemented"),
            _ => throw new ArgumentException($"Unknown discovery strategy: {sourceDefinition.Discovery.Strategy}")
        };

        return Task.FromResult(new DiscoveryResult
        {
            SourceId = sourceDefinition.SourceId,
            Links = links,
            Urls = links.Select(l => new DiscoveredSource(
                l.Url, 
                l.SourceId, 
                l.Metadata, 
                l.DiscoveredAt)).ToList()
        });
    }

    /// <summary>
    /// Discovers a single static URL.
    /// </summary>
    private IReadOnlyList<DiscoveredLink> DiscoverStaticUrl(SourceDefinition source)
    {
        var url = source.Discovery.StaticUrl;
        if (string.IsNullOrEmpty(url))
            throw new ArgumentException("StaticUrl is required for static_url strategy", nameof(source));

        return new List<DiscoveredLink>
        {
            new()
            {
                SourceId = source.SourceId,
                Url = url,
                UrlHash = ComputeSha256Hash(url),
                DocumentCount = null,
                TotalSizeBytes = null,
                Metadata = new Dictionary<string, object>(),
                DiscoveredAt = DateTime.UtcNow
            }
        };
    }

    /// <summary>
    /// Discovers URLs from a URL pattern with year range.
    /// </summary>
    private IReadOnlyList<DiscoveredLink> DiscoverUrlPattern(SourceDefinition source)
    {
        if (source.Discovery.UrlPattern == null)
            throw new ArgumentException("UrlPattern is required for url_pattern strategy", nameof(source));

        return _expander.Expand(source.Discovery.UrlPattern, source.SourceId);
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
