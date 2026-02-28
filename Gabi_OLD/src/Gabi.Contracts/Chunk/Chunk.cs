namespace Gabi.Contracts.Chunk;

/// <summary>
/// Tipo de chunk (seção do documento).
/// </summary>
public enum ChunkType
{
    /// <summary>Chunk de conteúdo genérico.</summary>
    Content,
    
    /// <summary>Chunk de título/cabeçalho.</summary>
    Title,
    
    /// <summary>Chunk de relatório.</summary>
    Report,
    
    /// <summary>Chunk de voto.</summary>
    Vote,
    
    /// <summary>Chunk de decisão.</summary>
    Decision,
    
    /// <summary>Chunk de norma/artigo.</summary>
    Article,
    
    /// <summary>Chunk de enunciado.</summary>
    Statement
}

/// <summary>
/// Representa um chunk (fragmento) de um documento.
/// </summary>
/// <param name="Index">Índice sequencial do chunk.</param>
/// <param name="Text">Texto do chunk.</param>
/// <param name="TokenCount">Número aproximado de tokens.</param>
/// <param name="Type">Tipo/seção do chunk.</param>
/// <param name="SectionType">Tipo de seção específica: "artigo", "paragrafo", "ementa", "voto", etc.</param>
/// <param name="Metadata">Metadados adicionais.</param>
public record Chunk(
    int Index,
    string Text,
    int TokenCount,
    ChunkType Type,
    string? SectionType = null,
    IReadOnlyDictionary<string, object>? Metadata = null
)
{
    /// <summary>Contagem de caracteres.</summary>
    public int CharCount => Text?.Length ?? 0;
}

/// <summary>
/// Resultado do chunking de um documento.
/// </summary>
/// <param name="DocumentId">ID do documento.</param>
/// <param name="Chunks">Chunks gerados.</param>
/// <param name="TotalTokens">Total de tokens.</param>
/// <param name="Strategy">Estratégia: legal_hierarchical, whole_document, semantic_section.</param>
public record ChunkingResult(
    string DocumentId,
    IReadOnlyList<Chunk> Chunks,
    int TotalTokens,
    string Strategy = "legal_hierarchical"
)
{
    /// <summary>Total de chunks.</summary>
    public int TotalChunks => Chunks?.Count ?? 0;
}
