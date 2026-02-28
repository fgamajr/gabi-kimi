using Gabi.Contracts.Ingest;

namespace Gabi.Contracts.Graph;

public interface IDocumentRelationshipExtractor
{
    IReadOnlyList<DocumentRelation> Extract(CanonicalTextDocument document);
}
