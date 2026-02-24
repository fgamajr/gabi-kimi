namespace Gabi.Contracts.Ingest;

/// <summary>
/// Canonical textual contract used by ingest before chunk/embed/index.
/// </summary>
public record CanonicalTextDocument
{
    public string SourceId { get; init; } = string.Empty;
    public string ExternalId { get; init; } = string.Empty;
    public string? Title { get; init; }
    public string Content { get; init; } = string.Empty;
    public string ContentType { get; init; } = "text/plain";
    public string Language { get; init; } = "pt-BR";
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = new Dictionary<string, object>();
}

/// <summary>
/// Media payload used to project audio/video metadata + transcript into canonical text.
/// </summary>
public record MediaProjectionInput
{
    public string SourceId { get; init; } = string.Empty;
    public string ExternalId { get; init; } = string.Empty;
    public string? MediaUrl { get; init; }
    public string? Title { get; init; }
    public string? TranscriptText { get; init; }
    public string? SummaryText { get; init; }
    public string? SessionType { get; init; }
    public string? Chamber { get; init; }
    public int? DurationSeconds { get; init; }
    public string? TranscriptConfidence { get; init; }
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = new Dictionary<string, object>();
}
