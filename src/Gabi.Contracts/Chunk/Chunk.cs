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
public record Chunk(
    int Index,
    string Text,
    int TokenCount,
    ChunkType Type
);
