namespace Gabi.Contracts.Media;

public record MediaUploadResponse(
    long MediaItemId,
    Guid JobId,
    string Status,
    string Message);

public record MediaItemStatusResponse(
    long Id,
    string SourceId,
    string ExternalId,
    string TranscriptStatus,
    string? LastError,
    DateTime CreatedAt,
    DateTime UpdatedAt);
