namespace Gabi.Contracts.Ingest;

/// <summary>
/// Normalizes and validates textual documents before persistence in ingest v1.
/// </summary>
public interface ICanonicalDocumentNormalizer
{
    CanonicalTextDocument Normalize(CanonicalTextDocument document);
}

/// <summary>
/// Projects media metadata/transcript into canonical textual representation.
/// </summary>
public interface IMediaTextProjector
{
    CanonicalTextDocument Project(MediaProjectionInput input);
}
