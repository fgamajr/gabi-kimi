using Gabi.Contracts.Chunk;

namespace Gabi.Contracts.Parse;

/// <summary>
/// Representa um documento parseado e pronto para processamento.
/// </summary>
/// <param name="DocumentId">ID único do documento.</param>
/// <param name="SourceId">ID da fonte de origem.</param>
/// <param name="Title">Título do documento.</param>
/// <param name="Content">Conteúdo textual completo.</param>
/// <param name="Fingerprint">Hash SHA256 do conteúdo.</param>
/// <param name="Chunks">Lista de chunks do documento.</param>
/// <param name="Metadata">Metadados adicionais.</param>
public record ParsedDocument(
    string DocumentId,
    string SourceId,
    string Title,
    string Content,
    string Fingerprint,
    IReadOnlyList<Chunk.Chunk> Chunks,
    IReadOnlyDictionary<string, object> Metadata
);
