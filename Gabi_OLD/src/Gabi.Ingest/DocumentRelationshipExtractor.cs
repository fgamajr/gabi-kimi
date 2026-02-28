using System.Text.RegularExpressions;
using Gabi.Contracts.Graph;
using Gabi.Contracts.Ingest;

namespace Gabi.Ingest;

/// <summary>
/// Regex-based extraction of legal citations and cross-references from Brazilian legal documents.
/// </summary>
public sealed class DocumentRelationshipExtractor : IDocumentRelationshipExtractor
{
    private static readonly Regex AcordaoPattern = new(
        @"Acórdão\s+(\d+/\d{4})[-–]TCU", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex LeiPattern = new(
        @"Lei\s+n[°º.]?\s?(\d+[.,/]\d+)", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex ProcessoPattern = new(
        @"Processo\s+(\d+\.\d+/\d{4})", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex SumulaPattern = new(
        @"Súmula\s+(?:TCU\s+)?n?[°º.]?\s?(\d+)", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public IReadOnlyList<DocumentRelation> Extract(CanonicalTextDocument document)
    {
        var relations = new List<DocumentRelation>();
        var seen = new HashSet<(string Ref, string Type)>();
        var content = document.Content ?? string.Empty;
        var sourceField = "content";

        ExtractFromContent(content, sourceField, relations, seen);
        ExtractFromMetadata(document.Metadata, relations, seen);

        return relations;
    }

    private static void ExtractFromContent(string content, string sourceField,
        List<DocumentRelation> relations, HashSet<(string, string)> seen)
    {
        foreach (Match m in AcordaoPattern.Matches(content))
        {
            var refText = $"Acórdão {m.Groups[1].Value}-TCU";
            if (seen.Add((refText, "cites")))
                relations.Add(new DocumentRelation(refText, "cites", 0.9f, sourceField));
        }

        foreach (Match m in LeiPattern.Matches(content))
        {
            var refText = $"Lei {m.Groups[1].Value}";
            if (seen.Add((refText, "references")))
                relations.Add(new DocumentRelation(refText, "references", 0.85f, sourceField));
        }

        foreach (Match m in ProcessoPattern.Matches(content))
        {
            var refText = $"Processo {m.Groups[1].Value}";
            if (seen.Add((refText, "related_process")))
                relations.Add(new DocumentRelation(refText, "related_process", 0.8f, sourceField));
        }

        foreach (Match m in SumulaPattern.Matches(content))
        {
            var refText = $"Súmula TCU {m.Groups[1].Value}";
            if (seen.Add((refText, "cites")))
                relations.Add(new DocumentRelation(refText, "cites", 0.9f, sourceField));
        }
    }

    private static void ExtractFromMetadata(IReadOnlyDictionary<string, object> metadata,
        List<DocumentRelation> relations, HashSet<(string, string)> seen)
    {
        // Check 'comentario' field for revoga/altera patterns
        if (metadata.TryGetValue("comentario", out var comentarioObj) && comentarioObj is string comentario
            && !string.IsNullOrWhiteSpace(comentario))
        {
            var lower = comentario.ToLowerInvariant();
            if (lower.Contains("revoga"))
            {
                // Try to extract what is being revoked
                foreach (Match m in AcordaoPattern.Matches(comentario))
                {
                    var refText = $"Acórdão {m.Groups[1].Value}-TCU";
                    if (seen.Add((refText, "revokes")))
                        relations.Add(new DocumentRelation(refText, "revokes", 0.95f, "metadata:comentario"));
                }
            }
            if (lower.Contains("altera"))
            {
                foreach (Match m in AcordaoPattern.Matches(comentario))
                {
                    var refText = $"Acórdão {m.Groups[1].Value}-TCU";
                    if (seen.Add((refText, "amends")))
                        relations.Add(new DocumentRelation(refText, "amends", 0.95f, "metadata:comentario"));
                }
            }
        }

        // Check DOU cross-references in artigo field
        if (metadata.TryGetValue("artigo", out var artigoObj) && artigoObj is string artigo
            && !string.IsNullOrWhiteSpace(artigo))
        {
            ExtractFromContent(artigo, "metadata:artigo", relations, seen);
        }
    }
}
