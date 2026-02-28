using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Gabi.Fetch;

namespace Gabi.Worker.Jobs.Fetch;

internal static class DouZipXmlExtractor
{
    private static readonly string[] TitleKeys = ["titulo", "title", "identifica", "ementa", "headline"];
    private static readonly string[] ContentKeys = ["texto", "conteudo", "content", "body", "p", "article", "textointegral"];
    private static readonly string[] DateKeys = ["data", "datapublicacao", "pubdate", "publicationdate"];
    private static readonly string[] SectionKeys = ["secao", "section"];
    private static readonly string[] PageKeys = ["pagina", "page", "pag"];

    internal static IReadOnlyList<DouZipXmlDocument> Extract(byte[] zipBytes, string sourceUrl)
    {
        var docs = new List<DouZipXmlDocument>(256);
        using var stream = new MemoryStream(zipBytes);
        using var archive = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: false);

        foreach (var entry in archive.Entries)
        {
            if (!entry.FullName.EndsWith(".xml", StringComparison.OrdinalIgnoreCase))
                continue;

            using var entryStream = entry.Open();
            using var ms = new MemoryStream();
            entryStream.CopyTo(ms);
            var xmlBytes = ms.ToArray();
            var xmlText = Decode(xmlBytes);
            if (string.IsNullOrWhiteSpace(xmlText))
                continue;

            XDocument xml;
            try
            {
                xml = XDocument.Parse(xmlText, LoadOptions.None);
            }
            catch
            {
                continue;
            }

            var title = ExtractFirst(xml.Root, TitleKeys);
            var content = ExtractContent(xml);
            if (string.IsNullOrWhiteSpace(content))
                continue;

            var section = ExtractFirst(xml.Root, SectionKeys) ?? InferSectionFromPath(entry.FullName) ?? InferSectionFromUrl(sourceUrl);
            var publicationDate = ExtractDate(xml.Root) ?? InferDateFromPath(entry.FullName) ?? InferDateFromUrl(sourceUrl);
            var page = ExtractFirst(xml.Root, PageKeys) ?? InferPageFromPath(entry.FullName);

            var docId = ExtractDocumentId(xml.Root);
            var externalId = BuildStableExternalId(sourceUrl, entry.FullName, docId, title, content);

            var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
            {
                ["format"] = "xml",
                ["archive_format"] = "zip",
                ["xml_entry_path"] = entry.FullName
            };
            if (!string.IsNullOrWhiteSpace(section))
            {
                metadata["secao"] = section!;
                metadata["section"] = section!;
            }
            if (!string.IsNullOrWhiteSpace(publicationDate))
            {
                metadata["data_publicacao"] = publicationDate!;
                metadata["publication_date"] = publicationDate!;
            }
            if (!string.IsNullOrWhiteSpace(page))
            {
                metadata["pagina"] = page!;
                metadata["page_start"] = page!;
                metadata["page_end"] = page!;
            }
            metadata["issue_type"] = InferIssueType(entry.FullName, sourceUrl);

            docs.Add(new DouZipXmlDocument(externalId, docId, title, content, metadata));
        }

        return docs;
    }

    private static string Decode(byte[] bytes)
    {
        string result;
        try
        {
            result = Encoding.UTF8.GetString(bytes);
        }
        catch
        {
            result = Encoding.Latin1.GetString(bytes);
        }

        // Strip UTF-8 BOM if present
        if (result.Length > 0 && result[0] == '\uFEFF')
            result = result[1..];

        return result;
    }

    private static string? ExtractFirst(XElement? root, string[] keys)
    {
        if (root == null)
            return null;

        foreach (var key in keys)
        {
            var element = root
                .Descendants()
                .FirstOrDefault(e => e.Name.LocalName.Equals(key, StringComparison.OrdinalIgnoreCase));
            if (element != null)
            {
                var value = Transforms.NormalizeWhitespace(element.Value);
                if (!string.IsNullOrWhiteSpace(value))
                    return value;
            }

            var attr = root
                .DescendantsAndSelf()
                .Attributes()
                .FirstOrDefault(a => a.Name.LocalName.Equals(key, StringComparison.OrdinalIgnoreCase));
            if (attr != null)
            {
                var value = Transforms.NormalizeWhitespace(attr.Value);
                if (!string.IsNullOrWhiteSpace(value))
                    return value;
            }
        }

        return null;
    }

    private static string ExtractContent(XDocument xml)
    {
        var candidates = new List<string>(512);
        foreach (var element in xml.Descendants())
        {
            if (element.HasElements)
                continue;

            var local = element.Name.LocalName.ToLowerInvariant();
            if (ContentKeys.Contains(local, StringComparer.OrdinalIgnoreCase) || local.StartsWith("text", StringComparison.OrdinalIgnoreCase))
            {
                var normalized = Transforms.NormalizeWhitespace(element.Value);
                if (!string.IsNullOrWhiteSpace(normalized) && normalized.Length > 10)
                    candidates.Add(normalized);
            }
        }

        if (candidates.Count == 0)
        {
            foreach (var element in xml.Descendants().Where(e => !e.HasElements))
            {
                var normalized = Transforms.NormalizeWhitespace(element.Value);
                if (!string.IsNullOrWhiteSpace(normalized) && normalized.Length > 20)
                    candidates.Add(normalized);
            }
        }

        var joined = string.Join("\n", candidates.Distinct(StringComparer.OrdinalIgnoreCase).Take(500));
        return FetchContentConverter.TruncateText(Transforms.NormalizeWhitespace(joined), maxChars: 200_000);
    }

    private static string? ExtractDocumentId(XElement? root)
    {
        if (root == null)
            return null;

        var idAttr = root.DescendantsAndSelf().Attributes()
            .FirstOrDefault(a => a.Name.LocalName.Equals("id", StringComparison.OrdinalIgnoreCase)
                              || a.Name.LocalName.Equals("documentid", StringComparison.OrdinalIgnoreCase)
                              || a.Name.LocalName.Equals("documento_id", StringComparison.OrdinalIgnoreCase));
        if (idAttr != null && !string.IsNullOrWhiteSpace(idAttr.Value))
            return idAttr.Value.Trim();

        return null;
    }

    private static string BuildStableExternalId(
        string sourceUrl,
        string entryPath,
        string? docId,
        string? title,
        string content)
    {
        var seed = $"{sourceUrl}|{entryPath}|{docId}|{title}|{content[..Math.Min(256, content.Length)]}";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(seed));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string? ExtractDate(XElement? root)
    {
        var raw = ExtractFirst(root, DateKeys);
        if (string.IsNullOrWhiteSpace(raw))
            return null;

        if (DateTime.TryParse(raw, out var parsed))
            return parsed.ToString("yyyy-MM-dd");

        return null;
    }

    private static string? InferDateFromPath(string value)
    {
        var match = Regex.Match(value, @"(?<y>20\d{2})[-_](?<m>\d{2})[-_](?<d>\d{2})", RegexOptions.CultureInvariant);
        if (!match.Success)
            return null;
        return $"{match.Groups["y"].Value}-{match.Groups["m"].Value}-{match.Groups["d"].Value}";
    }

    private static string? InferDateFromUrl(string value) => InferDateFromPath(value);

    private static string? InferSectionFromPath(string value)
    {
        var lower = value.ToLowerInvariant();
        if (lower.Contains("do1", StringComparison.Ordinal))
            return "do1";
        if (lower.Contains("do2", StringComparison.Ordinal))
            return "do2";
        if (lower.Contains("do3", StringComparison.Ordinal))
            return "do3";
        return null;
    }

    private static string? InferSectionFromUrl(string value) => InferSectionFromPath(value);

    private static string? InferPageFromPath(string value)
    {
        var match = Regex.Match(value, @"(?:pag|page|p)[-_]?(?<p>\d{1,4})", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        if (match.Success)
            return match.Groups["p"].Value;
        return null;
    }

    private static string InferIssueType(string entryPath, string sourceUrl)
    {
        if (entryPath.Contains("extra", StringComparison.OrdinalIgnoreCase)
            || sourceUrl.Contains("extra", StringComparison.OrdinalIgnoreCase))
            return "extra";
        return "ordinary";
    }
}

internal sealed record DouZipXmlDocument(
    string ExternalId,
    string? DocumentId,
    string? Title,
    string Content,
    IReadOnlyDictionary<string, object> Metadata);
