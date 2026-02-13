namespace Gabi.Contracts.Parse;

/// <summary>
/// Interface para parser de documentos.
/// </summary>
public interface IDocumentParser
{
    /// <summary>
    /// Tipos MIME suportados.
    /// </summary>
    IReadOnlyList<string> SupportedMimeTypes { get; }
    
    /// <summary>
    /// Extensões de arquivo suportadas.
    /// </summary>
    IReadOnlyList<string> SupportedExtensions { get; }
    
    /// <summary>
    /// Parse de conteúdo completo (não-streaming).
    /// </summary>
    Task<ParseResult> ParseAsync(
        Stream content,
        ParseConfig config,
        CancellationToken ct = default);
    
    /// <summary>
    /// Parse via streaming (para arquivos grandes).
    /// </summary>
    IAsyncEnumerable<ParseBatch> ParseStreamingAsync(
        IAsyncEnumerable<string> textChunks,
        ParseConfig config,
        CancellationToken ct = default);
}

/// <summary>
/// Resultado de parsing (completo).
/// </summary>
public record ParseResult
{
    /// <summary>Documentos parseados.</summary>
    public IReadOnlyList<ParsedDocument> Documents { get; init; } = 
        new List<ParsedDocument>();
    
    /// <summary>Total de linhas/records processados.</summary>
    public int TotalRecords { get; init; }
    
    /// <summary>Erros durante parsing.</summary>
    public IReadOnlyList<ParseError> Errors { get; init; } = 
        new List<ParseError>();
    
    /// <summary>Sucesso.</summary>
    public bool Success => Errors.Count == 0;
}

/// <summary>
/// Batch de parsing (streaming).
/// </summary>
public record ParseBatch
{
    /// <summary>Índice do batch.</summary>
    public int BatchIndex { get; init; }
    
    /// <summary>Documentos neste batch.</summary>
    public IReadOnlyList<ParsedDocument> Documents { get; init; } = 
        new List<ParsedDocument>();
    
    /// <summary>Linhas processadas até agora.</summary>
    public int RowsProcessed { get; init; }
}

/// <summary>
/// Erro de parsing.
/// </summary>
public record ParseError
{
    /// <summary>Linha/record afetado.</summary>
    public int? RowNumber { get; init; }
    
    /// <summary>Mensagem de erro.</summary>
    public string Message { get; init; } = string.Empty;
    
    /// <summary>Stack trace (se disponível).</summary>
    public string? StackTrace { get; init; }
}
