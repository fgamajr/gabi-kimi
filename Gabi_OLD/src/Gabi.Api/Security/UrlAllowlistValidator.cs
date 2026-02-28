using System.Net;
using System.Text.RegularExpressions;

namespace Gabi.Api.Security;

public sealed class UrlAllowlistValidator
{
    private static readonly HashSet<string> BlockedHosts = new(StringComparer.OrdinalIgnoreCase)
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "metadata.azure.internal"
    };

    private static readonly HashSet<string> BlockedMetadataIps = new(StringComparer.OrdinalIgnoreCase)
    {
        "169.254.169.254",
        "100.100.100.200",
        "169.254.170.2"
    };

    private readonly string[] _allowedPatterns;
    private readonly ILogger<UrlAllowlistValidator> _logger;

    public UrlAllowlistValidator(IConfiguration configuration, ILogger<UrlAllowlistValidator> logger)
    {
        _allowedPatterns = configuration
            .GetSection("Gabi:Media:AllowedUrlPatterns")
            .Get<string[]>() ?? Array.Empty<string>();
        _logger = logger;
    }

    public async Task<bool> IsAllowedAsync(string url, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(url))
            return false;

        if (!Uri.TryCreate(url.Trim(), UriKind.Absolute, out var uri))
            return false;

        if (!string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
            return false;

        if (_allowedPatterns.Length == 0)
        {
            _logger.LogWarning("Media URL allowlist is empty; blocking URL {Url}", url);
            return false;
        }

        if (BlockedHosts.Contains(uri.Host))
            return false;

        if (!MatchesAnyAllowlist(uri))
            return false;

        if (IPAddress.TryParse(uri.Host, out var ip))
            return !IsBlockedIp(ip);

        try
        {
            var resolved = await Dns.GetHostAddressesAsync(uri.Host, ct);
            if (resolved.Length == 0)
                return false;

            foreach (var address in resolved)
            {
                if (IsBlockedIp(address))
                    return false;
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(
                ex,
                "DNS resolution failed for allowlisted host {Host}; blocking URL {Url}",
                uri.Host,
                url);
            return false;
        }

        return true;
    }

    private bool MatchesAnyAllowlist(Uri uri)
    {
        var input = uri.ToString();
        foreach (var pattern in _allowedPatterns)
        {
            if (string.IsNullOrWhiteSpace(pattern))
                continue;

            var regex = WildcardPatternToRegex(pattern.Trim());
            if (Regex.IsMatch(input, regex, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
                return true;
        }

        return false;
    }

    private static string WildcardPatternToRegex(string pattern)
    {
        var escaped = Regex.Escape(pattern).Replace("\\*", ".*");
        return $"^{escaped}$";
    }

    private static bool IsBlockedIp(IPAddress ip)
    {
        if (ip.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6)
        {
            if (IPAddress.IsLoopback(ip))
                return true;

            var bytes = ip.GetAddressBytes();
            var first = bytes[0];
            var second = bytes[1];

            var isUniqueLocal = (first & 0xFE) == 0xFC;
            var isLinkLocal = first == 0xFE && (second & 0xC0) == 0x80;
            return isUniqueLocal || isLinkLocal;
        }

        var bytes4 = ip.GetAddressBytes();
        if (bytes4.Length != 4)
            return true;

        if (BlockedMetadataIps.Contains(ip.ToString()))
            return true;

        var b0 = bytes4[0];
        var b1 = bytes4[1];

        if (b0 == 10) return true;
        if (b0 == 127) return true;
        if (b0 == 169 && b1 == 254) return true;
        if (b0 == 192 && b1 == 168) return true;
        if (b0 == 172 && b1 >= 16 && b1 <= 31) return true;

        return false;
    }
}
