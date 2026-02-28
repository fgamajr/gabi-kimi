using System.Net;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Diagnostics;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class DouPublicMonthlyDriver
{
    private static readonly string[] PortugueseMonths =
    {
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    };

    private static readonly Regex ZipHrefRegex = new(
        @"href=""([^""]*\.zip[^""]*)""",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var baseUrl = ResolveBaseUrl(config);
        var sections = DouDiscoveryDriver.ResolveDouSections(config);
        var current = config.SnapshotAt ?? DateTime.UtcNow;
        var startYear = DouDiscoveryDriver.ResolvePositiveInt(config, "start_year", current.Year);
        var endYear = ResolveEndYear(config, current.Year);
        if (endYear < startYear)
            (startYear, endYear) = (endYear, startYear);

        var startMonth = Math.Clamp(DouDiscoveryDriver.ResolvePositiveInt(config, "start_month", 1), 1, 12);
        var endMonth = Math.Clamp(DouDiscoveryDriver.ResolvePositiveInt(config, "end_month", 12), 1, 12);
        var resumeYear = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_dou_year", 0);
        var resumeMonth = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_dou_month", 0);

        for (var year = startYear; year <= endYear; year++)
        {
            var monthFrom = year == startYear ? startMonth : 1;
            var monthTo = year == endYear ? endMonth : 12;
            if (year == current.Year)
                monthTo = Math.Min(monthTo, current.Month);
            if (monthTo < monthFrom)
                (monthFrom, monthTo) = (monthTo, monthFrom);

            for (var month = monthFrom; month <= monthTo; month++)
            {
                if (resumeYear > 0 && (year < resumeYear || (year == resumeYear && month < resumeMonth)))
                    continue;

                ct.ThrowIfCancellationRequested();

                var monthName = PortugueseMonths[month - 1];
                var pageUrl = $"{baseUrl}?ano={year}&mes={monthName}";

                string? html;
                try
                {
                    html = await FetchHtmlViaCurlAsync(new Uri(pageUrl), httpPolicy, ct);
                }
                catch (Exception ex) when (!ct.IsCancellationRequested)
                {
                    Console.Error.WriteLine($"[DouPublic] fetch failed year={year} month={month} url={pageUrl} err={ex.Message}");
                    continue;
                }

                if (string.IsNullOrWhiteSpace(html))
                    continue;

                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var zipMatches = ZipHrefRegex.Matches(html);
                Console.Error.WriteLine($"[DouPublic] year={year} month={month} href_zip_matches={zipMatches.Count}");

                foreach (Match match in zipMatches)
                {
                    if (!match.Success)
                        continue;

                    var href = WebUtility.HtmlDecode(match.Groups[1].Value);
                    if (string.IsNullOrWhiteSpace(href))
                        continue;

                    var matchesSection = false;
                    foreach (var section in sections)
                    {
                        if (href.Contains(section, StringComparison.OrdinalIgnoreCase))
                        {
                            matchesSection = true;
                            break;
                        }
                    }
                    if (!matchesSection)
                        continue;

                    var absoluteUrl = MakeAbsolute(href);
                    if (absoluteUrl == null || !seen.Add(absoluteUrl))
                        continue;

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = strategyKey,
                        ["driver"] = "dou_public_monthly_v1",
                        ["diario_tipo"] = "DOU",
                        ["document_kind"] = "ato_administrativo",
                        ["year"] = year,
                        ["month"] = month,
                        ["source_origin_url"] = absoluteUrl,
                        ["source_view_url"] = pageUrl,
                        ["source_download_url"] = absoluteUrl
                    };

                    yield return new DiscoveredSource(absoluteUrl, sourceId, metadata, DateTime.UtcNow);
                }

                if (httpPolicy.RequestDelayMs > 0)
                    await Task.Delay(httpPolicy.RequestDelayMs, ct);
            }
        }
    }

    private static string ResolveBaseUrl(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("base_url", out var el)
            && el.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(el.GetString()))
        {
            return el.GetString()!.TrimEnd('/');
        }

        return "https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados";
    }

    private static int ResolveEndYear(DiscoveryConfig config, int currentYear)
    {
        if (config.Extra != null && config.Extra.TryGetValue("end_year", out var v))
        {
            if (v.ValueKind == JsonValueKind.String
                && v.GetString()?.Equals("current", StringComparison.OrdinalIgnoreCase) == true)
                return currentYear;

            if (v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var i) && i > 0)
                return i;

            if (v.ValueKind == JsonValueKind.String && int.TryParse(v.GetString(), out var i2) && i2 > 0)
                return i2;
        }

        return currentYear;
    }

    private static string? MakeAbsolute(string href)
    {
        if (Uri.TryCreate(href, UriKind.Absolute, out var abs))
            return abs.ToString();

        if (href.StartsWith('/'))
        {
            if (Uri.TryCreate(new Uri("https://www.in.gov.br"), href, out var rel))
                return rel.ToString();
        }

        return null;
    }

    private static async Task<string> FetchHtmlViaCurlAsync(Uri url, DiscoveryHttpRequestPolicy httpPolicy, CancellationToken ct)
    {
        if (!url.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
            && !url.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("DOU public monthly driver supports only HTTP/HTTPS URLs.");

        var timeoutSeconds = Math.Max(1, (int)Math.Ceiling(httpPolicy.RequestTimeout.TotalSeconds));
        var userAgent = httpPolicy.UserAgents.Count > 0 ? httpPolicy.UserAgents[0] : UserAgentCatalog.Default[0];

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
        psi.ArgumentList.Add("--user-agent");
        psi.ArgumentList.Add(userAgent);
        psi.ArgumentList.Add("--header");
        psi.ArgumentList.Add("Accept: text/html,application/xhtml+xml,*/*");
        psi.ArgumentList.Add("--header");
        psi.ArgumentList.Add("Accept-Language: pt-BR,pt;q=0.9,en;q=0.8");
        psi.ArgumentList.Add(url.AbsoluteUri);

        using var process = Process.Start(psi) ?? throw new InvalidOperationException("Failed to start curl process.");
        var stdoutTask = process.StandardOutput.ReadToEndAsync(ct);
        var stderrTask = process.StandardError.ReadToEndAsync(ct);
        await process.WaitForExitAsync(ct);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        if (process.ExitCode != 0)
            throw new InvalidOperationException($"curl fallback failed (exit={process.ExitCode}): {stderr}");

        return stdout;
    }
}
