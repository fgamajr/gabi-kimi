using Gabi.Contracts.Ingest;

namespace Gabi.Ingest;

public sealed class MediaTextProjector : IMediaTextProjector
{
    private readonly ICanonicalDocumentNormalizer _normalizer;

    public MediaTextProjector(ICanonicalDocumentNormalizer normalizer)
    {
        _normalizer = normalizer;
    }

    public CanonicalTextDocument Project(MediaProjectionInput input)
    {
        ArgumentNullException.ThrowIfNull(input);

        var sections = new List<string>(3);
        if (!string.IsNullOrWhiteSpace(input.Title))
            sections.Add($"# {input.Title.Trim()}");

        if (!string.IsNullOrWhiteSpace(input.SummaryText))
            sections.Add($"## Summary\n{input.SummaryText.Trim()}");

        if (!string.IsNullOrWhiteSpace(input.TranscriptText))
            sections.Add($"## Transcript\n{input.TranscriptText.Trim()}");

        if (sections.Count == 0)
            throw new InvalidOperationException("Media projection requires transcript_text or summary_text.");

        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in input.Metadata)
            metadata[item.Key] = item.Value;

        metadata["origin"] = "media_projection_v1";
        metadata["media.external_id"] = input.ExternalId;
        metadata["media.url"] = input.MediaUrl ?? string.Empty;
        metadata["media.session_type"] = input.SessionType ?? string.Empty;
        metadata["media.chamber"] = input.Chamber ?? string.Empty;
        metadata["media.duration_seconds"] = input.DurationSeconds ?? 0;
        metadata["media.transcript_confidence"] = input.TranscriptConfidence ?? string.Empty;

        var canonical = new CanonicalTextDocument
        {
            SourceId = input.SourceId,
            ExternalId = input.ExternalId,
            Title = input.Title,
            Content = string.Join("\n\n", sections),
            ContentType = "text/markdown",
            Language = "pt-BR",
            Metadata = metadata
        };

        return _normalizer.Normalize(canonical);
    }
}
