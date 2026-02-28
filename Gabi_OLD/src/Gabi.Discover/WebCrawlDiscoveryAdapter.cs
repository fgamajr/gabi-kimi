using System.Text.Json;
using System.Text.RegularExpressions;
using System.Diagnostics;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

public sealed class WebCrawlDiscoveryAdapter : IDiscoveryAdapter
{
    private static readonly Regex HrefRegex = new("href\\s*=\\s*['\"](?<href>[^'\"#]+)['\"]", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private readonly HttpClient _httpClient;

    public string StrategyKey => "web_crawl";

    public WebCrawlDiscoveryAdapter(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var httpPolicy = DiscoveryHttpRequestPolicy.FromConfig(config);
        var driver = ResolveDriver(config);
        var rootUrl = ResolveRootUrl(config);
        if (string.IsNullOrWhiteSpace(rootUrl))
            throw new ArgumentException("web_crawl requires 'root_url' (or 'url') in discovery config", nameof(config));

        if (!Uri.TryCreate(rootUrl, UriKind.Absolute, out var rootUri))
            throw new ArgumentException($"Invalid root URL for web_crawl: {rootUrl}", nameof(config));

        var rules = ParseRules(config);
        var maxDepth = rules.TryGetValue("max_depth", out var depthObj) ? ParseInt(depthObj, 1) : 1;
        if (maxDepth < 0)
            maxDepth = 0;

        var paginationParam = rules.TryGetValue("pagination_param", out var paginationObj) ? paginationObj?.ToString() : null;
        var assetSelector = rules.TryGetValue("asset_selector", out var assetSel) ? assetSel?.ToString() : null;
        var linkSelector = rules.TryGetValue("link_selector", out var linkSel) ? linkSel?.ToString() : null;

        var visitedPages = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var yieldedAssets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var queue = new Queue<(Uri Url, int Depth)>();
        queue.Enqueue((rootUri, 0));

        while (queue.Count > 0)
        {
            ct.ThrowIfCancellationRequested();

            var (pageUrl, depth) = queue.Dequeue();
            if (!visitedPages.Add(pageUrl.AbsoluteUri))
                continue;

            string html;
            try
            {
                if (driver.Equals("curl_html_v1", StringComparison.OrdinalIgnoreCase))
                {
                    html = await FetchHtmlViaCurlAsync(pageUrl, httpPolicy, ct);
                }
                else
                {
                    using var req = new HttpRequestMessage(HttpMethod.Get, pageUrl);
                    httpPolicy.Apply(req);
                    using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    timeoutCts.CancelAfter(httpPolicy.RequestTimeout);
                    using var resp = await _httpClient.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, timeoutCts.Token);
                    if (!resp.IsSuccessStatusCode)
                    {
                        if (depth == 0)
                            throw new InvalidOperationException($"web_crawl root fetch failed with HTTP {(int)resp.StatusCode} for {pageUrl.AbsoluteUri}");
                        continue;
                    }

                    var mediaType = resp.Content.Headers.ContentType?.MediaType?.ToLowerInvariant() ?? string.Empty;
                    if (!string.IsNullOrEmpty(mediaType) && !mediaType.Contains("html") && !mediaType.Contains("xml") && !mediaType.Contains("text"))
                        continue;

                    html = await resp.Content.ReadAsStringAsync(ct);
                }
            }
            catch
            {
                if (depth == 0)
                    throw new InvalidOperationException($"web_crawl failed to fetch root URL: {pageUrl.AbsoluteUri}");
                continue;
            }

            foreach (var href in ExtractHrefs(html))
            {
                if (!Uri.TryCreate(pageUrl, href, out var absolute))
                    continue;

                if (!IsHttp(absolute))
                    continue;

                var absoluteUrl = absolute.AbsoluteUri;

                if (MatchesSelector(absoluteUrl, assetSelector))
                {
                    if (yieldedAssets.Add(absoluteUrl))
                    {
                        yield return new DiscoveredSource(
                            absoluteUrl,
                            sourceId,
                            new Dictionary<string, object>
                            {
                                ["strategy"] = StrategyKey,
                                ["crawl_depth"] = depth,
                                ["parent_url"] = pageUrl.AbsoluteUri
                            },
                            DateTime.UtcNow);
                    }

                    continue;
                }

                if (depth >= maxDepth)
                    continue;

                if (absolute.Host != rootUri.Host)
                    continue;

                if (IsPaginationLink(absolute, rootUri, paginationParam))
                {
                    queue.Enqueue((absolute, depth + 1));
                    continue;
                }

                if (!string.IsNullOrWhiteSpace(linkSelector) && !MatchesSelector(absoluteUrl, linkSelector))
                    continue;

                queue.Enqueue((absolute, depth + 1));
            }
        }
    }

    private static bool IsPaginationLink(Uri candidate, Uri rootUri, string? paginationParam)
    {
        if (string.IsNullOrWhiteSpace(paginationParam))
            return false;

        if (!candidate.Host.Equals(rootUri.Host, StringComparison.OrdinalIgnoreCase))
            return false;

        var query = candidate.Query;
        if (string.IsNullOrWhiteSpace(query))
            return false;

        var token = $"{paginationParam}=";
        return query.AsSpan().IndexOf(token.AsSpan(), StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static string? ResolveRootUrl(DiscoveryConfig config)
    {
        if (config.Extra != null && config.Extra.TryGetValue("root_url", out var rootEl) && rootEl.ValueKind == JsonValueKind.String)
            return rootEl.GetString();

        return config.Url;
    }

    private static string ResolveDriver(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("driver", out var driverEl)
            && driverEl.ValueKind == JsonValueKind.String)
        {
            return driverEl.GetString() ?? string.Empty;
        }

        return string.Empty;
    }

    private static Dictionary<string, object?> ParseRules(DiscoveryConfig config)
    {
        if (config.Extra == null || !config.Extra.TryGetValue("rules", out var rulesEl) || rulesEl.ValueKind != JsonValueKind.Object)
            return new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);

        var dict = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        foreach (var p in rulesEl.EnumerateObject())
        {
            dict[p.Name] = p.Value.ValueKind switch
            {
                JsonValueKind.String => p.Value.GetString(),
                JsonValueKind.Number => p.Value.TryGetInt32(out var i) ? i : p.Value.GetDouble(),
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                _ => p.Value.GetRawText()
            };
        }

        return dict;
    }

    private static int ParseInt(object? value, int fallback)
    {
        if (value == null)
            return fallback;

        return value switch
        {
            int i => i,
            long l => (int)l,
            double d => (int)d,
            string s when int.TryParse(s, out var i) => i,
            _ => fallback
        };
    }

    private static IEnumerable<string> ExtractHrefs(string html)
    {
        foreach (Match m in HrefRegex.Matches(html))
        {
            var href = m.Groups["href"].Value.Trim();
            if (!string.IsNullOrWhiteSpace(href))
                yield return href;
        }
    }

    private static bool IsHttp(Uri uri)
        => uri.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
           || uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase);

    private static bool MatchesSelector(string url, string? selector)
    {
        if (string.IsNullOrWhiteSpace(selector))
            return false;

        var notContains = Regex.Matches(selector, "not\\(\\[href\\*=['\"](?<v>[^'\"]+)['\"]\\]\\)", RegexOptions.IgnoreCase)
            .Select(m => m.Groups["v"].Value)
            .ToList();
        var notSuffixes = Regex.Matches(selector, "not\\(\\[href\\$=['\"](?<v>[^'\"]+)['\"]\\]\\)", RegexOptions.IgnoreCase)
            .Select(m => m.Groups["v"].Value)
            .ToList();

        var positiveSelector = Regex.Replace(
            selector,
            "not\\(\\[href(?:\\*|\\$)=['\"][^'\"]+['\"]\\]\\)",
            string.Empty,
            RegexOptions.IgnoreCase);

        var mustContains = Regex.Matches(positiveSelector, "href\\*=['\"](?<v>[^'\"]+)['\"]", RegexOptions.IgnoreCase)
            .Select(m => m.Groups["v"].Value)
            .ToList();
        var mustSuffixes = Regex.Matches(positiveSelector, "href\\$=['\"](?<v>[^'\"]+)['\"]", RegexOptions.IgnoreCase)
            .Select(m => m.Groups["v"].Value)
            .ToList();

        foreach (var part in mustContains)
        {
            if (!url.Contains(part, StringComparison.OrdinalIgnoreCase))
                return false;
        }

        if (mustSuffixes.Count > 0 && !mustSuffixes.Any(s => url.EndsWith(s, StringComparison.OrdinalIgnoreCase)))
            return false;

        if (notContains.Any(s => url.Contains(s, StringComparison.OrdinalIgnoreCase)))
            return false;

        if (notSuffixes.Any(s => url.EndsWith(s, StringComparison.OrdinalIgnoreCase)))
            return false;

        return true;
    }

    private static async Task<string> FetchHtmlViaCurlAsync(Uri url, DiscoveryHttpRequestPolicy httpPolicy, CancellationToken ct)
    {
        if (!IsHttp(url))
            throw new InvalidOperationException("curl_html_v1 supports only http/https URLs.");

        var timeoutSeconds = Math.Max(1, (int)Math.Ceiling(httpPolicy.RequestTimeout.TotalSeconds));

        var psi = new ProcessStartInfo
        {
            FileName = "curl",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false
        };
        psi.ArgumentList.Add("--fail");
        psi.ArgumentList.Add("--silent");
        psi.ArgumentList.Add("--show-error");
        psi.ArgumentList.Add("--location");
        psi.ArgumentList.Add("--http1.1");
        psi.ArgumentList.Add("--max-time");
        psi.ArgumentList.Add(timeoutSeconds.ToString());
        psi.ArgumentList.Add(url.AbsoluteUri);

        using var process = Process.Start(psi) ?? throw new InvalidOperationException("Failed to start curl process.");

        var stdoutTask = process.StandardOutput.ReadToEndAsync(ct);
        var stderrTask = process.StandardError.ReadToEndAsync(ct);
        await process.WaitForExitAsync(ct);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (process.ExitCode != 0)
            throw new InvalidOperationException($"curl_html_v1 failed (exit={process.ExitCode}): {stderr}");

        return stdout;
    }
}
