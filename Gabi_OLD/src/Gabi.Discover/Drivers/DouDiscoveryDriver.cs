using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class DouDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverDouInlabsXmlAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var endpointTemplate = ResolveDouEndpointTemplate(config);
        if (endpointTemplate.Contains("inlabs.in.gov.br", StringComparison.OrdinalIgnoreCase)
            && (!httpPolicy.Headers.TryGetValue("Cookie", out var cookie) || string.IsNullOrWhiteSpace(cookie)))
        {
            throw new ArgumentException("dou_inlabs_xml_v1 requires http.headers.Cookie (e.g. ${GABI_INLABS_COOKIE}) for inlabs.in.gov.br", nameof(config));
        }
        var sections = ResolveDouSections(config);
        var (startDate, endDate) = ResolveDouDateRange(config);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var resumeDateStr = DiscoveryAdapterHelpers.ReadResumeCursorString(config, "resume_dou_date");
        var resumeDate = resumeDateStr != null && DateTime.TryParse(resumeDateStr, out var rd) ? rd.Date : DateTime.MinValue;

        for (var date = startDate.Date; date <= endDate.Date; date = date.AddDays(1))
        {
            if (date < resumeDate)
                continue; // skip dates already fully processed before last checkpoint
            foreach (var section in sections)
            {
                ct.ThrowIfCancellationRequested();
                var dateText = date.ToString("yyyy-MM-dd");
                var endpoint = endpointTemplate
                    .Replace("{date}", dateText, StringComparison.OrdinalIgnoreCase)
                    .Replace("{section}", section, StringComparison.OrdinalIgnoreCase);

                using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, endpoint, httpPolicy, ct);
                if (resp == null || !resp.IsSuccessStatusCode)
                    continue;

                var body = await resp.Content.ReadAsStringAsync(ct);
                XDocument xml;
                try
                {
                    xml = XDocument.Parse(body, LoadOptions.None);
                }
                catch
                {
                    xml = new XDocument();
                }

                var foundArticles = false;
                foreach (var article in xml.Descendants().Where(x => x.Name.LocalName.Equals("article", StringComparison.OrdinalIgnoreCase)))
                {
                    foundArticles = true;
                    var link = ExtractDouArticleLink(article);
                    if (string.IsNullOrWhiteSpace(link) || !seen.Add(link))
                        continue;

                    var viewUrl = FirstNonEmpty(
                        ReadDouArticleValue(article, "urlTitle"),
                        ReadDouArticleValue(article, "url"),
                        ReadDouArticleValue(article, "href"),
                        link);
                    var downloadUrl = FirstNonEmpty(
                        ReadDouArticleValue(article, "urlPdf"),
                        link);

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = strategyKey,
                        ["driver"] = "dou_inlabs_xml_v1",
                        ["diario_tipo"] = "DOU",
                        ["document_kind"] = "ato_administrativo",
                        ["secao"] = section,
                        ["section"] = section,
                        ["data_publicacao"] = dateText,
                        ["publication_date"] = dateText,
                        ["orgao"] = ReadDouArticleValue(article, "orgao"),
                        ["edicao"] = ReadDouArticleValue(article, "edicao"),
                        ["pagina"] = ReadDouArticleValue(article, "pagina"),
                        ["ato_tipo"] = ReadDouArticleValue(article, "tipo"),
                        ["titulo"] = ReadDouArticleValue(article, "titulo"),
                        ["issue_type"] = InferIssueType(downloadUrl, ReadDouArticleValue(article, "edicao")),
                        ["source_origin_url"] = link,
                        ["source_view_url"] = viewUrl,
                        ["source_download_url"] = downloadUrl
                    };
                    if (LooksLikePdfUrl(downloadUrl))
                        metadata["source_pdf_url"] = downloadUrl;

                    yield return new DiscoveredSource(link, sourceId, metadata, DateTime.UtcNow);
                }

                // INLABS also serves a directory-like HTML page with downloadable files.
                // Fallback: discover direct ZIP/PDF assets when XML articles are not present.
                if (!foundArticles)
                {
                    foreach (var asset in ExtractDouListingAssets(body, endpoint, section))
                    {
                        if (!seen.Add(asset.Url))
                            continue;

                        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                        {
                            ["strategy"] = strategyKey,
                            ["driver"] = "dou_inlabs_xml_v1",
                            ["diario_tipo"] = "DOU",
                            ["document_kind"] = "ato_administrativo",
                            ["secao"] = section,
                            ["section"] = section,
                            ["data_publicacao"] = dateText,
                            ["publication_date"] = dateText,
                            ["issue_type"] = InferIssueType(asset.Url, null),
                            ["source_origin_url"] = asset.Url,
                            ["source_view_url"] = endpoint,
                            ["source_download_url"] = asset.Url,
                            ["source_asset_type"] = asset.AssetType
                        };
                        if (asset.AssetType == "pdf")
                            metadata["source_pdf_url"] = asset.Url;

                        yield return new DiscoveredSource(asset.Url, sourceId, metadata, DateTime.UtcNow);
                    }
                }

                if (httpPolicy.RequestDelayMs > 0)
                    await Task.Delay(httpPolicy.RequestDelayMs, ct);
            }
        }
    }

    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverDouMonthlyPatternAsync(
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var template = ResolveDouMonthlyTemplate(config);
        var sections = ResolveDouSections(config);
        var current = config.SnapshotAt ?? DateTime.UtcNow;
        var startYear = ResolvePositiveInt(config, "start_year", current.Year);
        var endYear = ResolvePositiveInt(config, "end_year", current.Year);
        if (endYear < startYear)
            (startYear, endYear) = (endYear, startYear);

        var startMonthDefault = startYear == current.Year ? 1 : 1;
        var endMonthDefault = endYear == current.Year ? current.Month : 12;
        var startMonth = Math.Clamp(ResolvePositiveInt(config, "start_month", startMonthDefault), 1, 12);
        var endMonth = Math.Clamp(ResolvePositiveInt(config, "end_month", endMonthDefault), 1, 12);
        var resumeDouYear = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_dou_year", 0);
        var resumeDouMonth = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_dou_month", 0);

        for (var year = startYear; year <= endYear; year++)
        {
            var monthFrom = year == startYear ? startMonth : 1;
            var monthTo = year == endYear ? endMonth : 12;
            if (monthTo < monthFrom)
                (monthFrom, monthTo) = (monthTo, monthFrom);

            for (var month = monthFrom; month <= monthTo; month++)
            {
                if (resumeDouYear > 0 && (year < resumeDouYear || (year == resumeDouYear && month < resumeDouMonth)))
                    continue; // skip months already fully processed before last checkpoint
                foreach (var section in sections)
                {
                    ct.ThrowIfCancellationRequested();
                    var url = template
                        .Replace("{year}", year.ToString(), StringComparison.OrdinalIgnoreCase)
                        .Replace("{month}", month.ToString("00"), StringComparison.OrdinalIgnoreCase)
                        .Replace("{section}", section, StringComparison.OrdinalIgnoreCase);

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = strategyKey,
                        ["driver"] = "dou_monthly_pattern_v1",
                        ["diario_tipo"] = "DOU",
                        ["document_kind"] = "ato_administrativo",
                        ["year"] = year,
                        ["month"] = month,
                        ["secao"] = section,
                        ["source_origin_url"] = url,
                        ["source_view_url"] = url,
                        ["source_download_url"] = url
                    };
                    if (LooksLikePdfUrl(url))
                        metadata["source_pdf_url"] = url;

                    yield return new DiscoveredSource(url, sourceId, metadata, DateTime.UtcNow);
                    await Task.Yield();
                }
            }
        }
    }

    internal static string ResolveDouEndpointTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        throw new ArgumentException("dou_inlabs_xml_v1 requires 'endpoint_template' in discovery config", nameof(config));
    }

    internal static string ResolveDouMonthlyTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null)
        {
            if (config.Extra.TryGetValue("url_template", out var urlTemplateEl)
                && urlTemplateEl.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(urlTemplateEl.GetString()))
            {
                return urlTemplateEl.GetString()!;
            }

            if (config.Extra.TryGetValue("endpoint_template", out var endpointTemplateEl)
                && endpointTemplateEl.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(endpointTemplateEl.GetString()))
            {
                return endpointTemplateEl.GetString()!;
            }
        }

        throw new ArgumentException("dou_monthly_pattern_v1 requires 'url_template' (or 'endpoint_template') in discovery config", nameof(config));
    }

    internal static string[] ResolveDouSections(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("sections", out var sectionsEl)
            && sectionsEl.ValueKind == JsonValueKind.Array)
        {
            var values = sectionsEl
                .EnumerateArray()
                .Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString())
                .Where(x => !string.IsNullOrWhiteSpace(x))
                .Select(x => x!)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            if (values.Length > 0)
                return values;
        }

        return ["do1"];
    }

    internal static (DateTime Start, DateTime End) ResolveDouDateRange(DiscoveryConfig config)
    {
        var today = (config.SnapshotAt ?? DateTime.UtcNow).Date;
        if (config.Params == null || !config.Params.TryGetValue("date_range", out var dateRange))
            return (today, today);

        if (dateRange is JsonElement je && je.ValueKind == JsonValueKind.Object)
        {
            var start = ParseDateValue(je, "start", today);
            var end = ParseDateValue(je, "end", today);
            if (end < start)
                (start, end) = (end, start);
            return (start, end);
        }

        return (today, today);
    }

    internal static int ResolvePositiveInt(DiscoveryConfig config, string key, int fallback)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue(key, out var value))
        {
            var parsed = value.ValueKind switch
            {
                JsonValueKind.Number when value.TryGetInt32(out var i) => i,
                JsonValueKind.String when int.TryParse(value.GetString(), out var i) => i,
                _ => fallback
            };
            if (parsed > 0)
                return parsed;
        }

        return fallback;
    }

    internal static DateTime ParseDateValue(JsonElement obj, string propertyName, DateTime fallback)
    {
        if (!obj.TryGetProperty(propertyName, out var value))
            return fallback;

        if (value.ValueKind != JsonValueKind.String)
            return fallback;

        var raw = value.GetString();
        if (string.IsNullOrWhiteSpace(raw))
            return fallback;

        // Support "current" → today, "current-{N}d" → today.AddDays(-N)
        if (raw.Equals("current", StringComparison.OrdinalIgnoreCase))
            return fallback; // fallback is already today

        var relMatch = Regex.Match(raw, @"^current-(\d+)d$", RegexOptions.IgnoreCase);
        if (relMatch.Success && int.TryParse(relMatch.Groups[1].Value, out var days))
            return fallback.AddDays(-days);

        if (DateTime.TryParse(raw, out var parsed))
            return parsed.Date;

        return fallback;
    }

    internal static string? ExtractDouArticleLink(XElement article)
    {
        var url = ReadDouArticleValue(article, "url");
        if (string.IsNullOrWhiteSpace(url))
            url = ReadDouArticleValue(article, "href");
        if (string.IsNullOrWhiteSpace(url))
            url = ReadDouArticleValue(article, "link");
        if (string.IsNullOrWhiteSpace(url))
            url = ReadDouArticleValue(article, "urlTitle");
        if (string.IsNullOrWhiteSpace(url))
            url = ReadDouArticleValue(article, "urlPdf");

        return string.IsNullOrWhiteSpace(url) ? null : url;
    }

    internal static string ReadDouArticleValue(XElement article, string key)
    {
        var attr = article.Attributes().FirstOrDefault(a => a.Name.LocalName.Equals(key, StringComparison.OrdinalIgnoreCase))?.Value;
        if (!string.IsNullOrWhiteSpace(attr))
            return attr!;

        var element = article.Elements().FirstOrDefault(e => e.Name.LocalName.Equals(key, StringComparison.OrdinalIgnoreCase))?.Value;
        if (!string.IsNullOrWhiteSpace(element))
            return element.Trim();

        return string.Empty;
    }

    private static string FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value!;
        }

        return string.Empty;
    }

    private static bool LooksLikePdfUrl(string? value)
        => !string.IsNullOrWhiteSpace(value) && value.Contains(".pdf", StringComparison.OrdinalIgnoreCase);

    private static string InferIssueType(string? url, string? edicao)
    {
        if (!string.IsNullOrWhiteSpace(edicao) && edicao.Contains("extra", StringComparison.OrdinalIgnoreCase))
            return "extra";
        if (!string.IsNullOrWhiteSpace(url) && url.Contains("extra", StringComparison.OrdinalIgnoreCase))
            return "extra";
        return "ordinary";
    }

    private static IEnumerable<DouListingAsset> ExtractDouListingAssets(string html, string endpoint, string section)
    {
        if (string.IsNullOrWhiteSpace(html))
            yield break;

        var endpointUri = Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) ? uri : null;
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var rx = new Regex(@"href=""(?<href>[^""]*(?:\?|&|&amp;)dl=[^""]+\.zip)""", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        var sectionToken = section.ToUpperInvariant();

        foreach (Match m in rx.Matches(html))
        {
            if (!m.Success)
                continue;
            var href = System.Net.WebUtility.HtmlDecode(m.Groups["href"].Value);
            if (string.IsNullOrWhiteSpace(href))
                continue;
            var lower = href.ToLowerInvariant();
            var isZip = lower.Contains(".zip", StringComparison.OrdinalIgnoreCase);
            if (!isZip)
                continue;
            if (!href.Contains(sectionToken, StringComparison.OrdinalIgnoreCase))
                continue;

            if (!TryResolveAbsoluteUrl(endpointUri, href, out var resolved))
                continue;
            if (!seen.Add(resolved))
                continue;

            yield return new DouListingAsset(resolved, "zip");
        }
    }

    private static bool TryResolveAbsoluteUrl(Uri? endpointUri, string href, out string resolved)
    {
        resolved = string.Empty;
        if (Uri.TryCreate(href, UriKind.Absolute, out var abs))
        {
            resolved = abs.ToString();
            return true;
        }

        if (endpointUri != null && Uri.TryCreate(endpointUri, href, out var rel))
        {
            resolved = rel.ToString();
            return true;
        }

        return false;
    }

    private sealed record DouListingAsset(string Url, string AssetType);
}
