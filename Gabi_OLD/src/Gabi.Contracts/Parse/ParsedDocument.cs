namespace Gabi.Contracts.Parse;

/// <summary>
/// Representa um documento parseado e pronto para processamento.
/// Tipo CANÔNICO do pipeline.
/// </summary>
public record ParsedDocument
{
    // Identificação
    /// <summary>ID único do documento.</summary>
    public string DocumentId { get; init; } = string.Empty;
    
    /// <summary>ID da fonte de origem.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>URL original (se disponível).</summary>
    public string? Url { get; init; }
    
    // Conteúdo principal
    /// <summary>Título do documento.</summary>
    public string? Title { get; init; }
    
    /// <summary>Conteúdo textual completo normalizado.</summary>
    public string Content { get; init; } = string.Empty;
    
    /// <summary>Preview do conteúdo (primeiros 500 chars).</summary>
    public string? ContentPreview => Content?.Length > 500 
        ? Content[..500] + "..." 
        : Content;
    
    // Metadados estruturados
    /// <summary>Campos do mapping que não são content: year, number, type, colegiado, relator, etc.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
    
    /// <summary>Campos de texto separados: text_relatorio, text_voto, text_acordao, etc.</summary>
    public IReadOnlyDictionary<string, string> TextFields { get; init; } = 
        new Dictionary<string, string>();
    
    // Técnicos
    /// <summary>Content-Type.</summary>
    public string ContentType { get; init; } = "text/plain";
    
    /// <summary>Idioma.</summary>
    public string Language { get; init; } = "pt-BR";
    
    /// <summary>Tamanho em bytes.</summary>
    public long? ContentSizeBytes { get; init; }
    
    /// <summary>Hash SHA256 do conteúdo (fingerprint).</summary>
    public string? ContentHash { get; init; }
}
