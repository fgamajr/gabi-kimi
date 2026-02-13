namespace Gabi.Contracts.Parse;

/// <summary>
/// Estratégias de parsing.
/// </summary>
public enum ParseStrategy
{
    CsvRowToDocument,
    HtmlToDocument,
    PdfToDocument,
    JsonToDocument,
    XmlToDocument
}

/// <summary>
/// Configuração de parsing de CSV.
/// </summary>
public record CsvParseConfig
{
    /// <summary>Linha do header (0-based).</summary>
    public int HeaderRow { get; init; } = 0;
    
    /// <summary>Linhas a pular antes do header.</summary>
    public int SkipRows { get; init; } = 0;
    
    /// <summary>Coluna que contém o ID do documento.</summary>
    public string? IdColumn { get; init; }
    
    /// <summary>Tamanho do batch para streaming.</summary>
    public int BatchSize { get; init; } = 100;
    
    /// <summary>Máximo de linhas a processar.</summary>
    public int? MaxRows { get; init; }
}

/// <summary>
/// Configuração de campo (field mapping).
/// </summary>
public record FieldMapping
{
    /// <summary>Coluna de origem no arquivo.</summary>
    public string Source { get; init; } = string.Empty;
    
    /// <summary>Transforms a aplicar.</summary>
    public IReadOnlyList<string> Transforms { get; init; } = Array.Empty<string>();
    
    /// <summary>Campo obrigatório.</summary>
    public bool Required { get; init; } = false;
    
    /// <summary>Armazenar em PostgreSQL.</summary>
    public bool Store { get; init; } = true;
    
    /// <summary>Indexar em Elasticsearch.</summary>
    public bool Index { get; init; } = false;
    
    /// <summary>Criar embeddings.</summary>
    public bool Chunk { get; init; } = false;
}

/// <summary>
/// Configuração de composição do documento.
/// </summary>
public record DocumentComposition
{
    /// <summary>Template de ID (ex: "acordao-{number}/{year}").</summary>
    public string? IdTemplate { get; init; }
    
    /// <summary>Template de título.</summary>
    public string? TitleTemplate { get; init; }
    
    /// <summary>Campos que compõem o conteúdo.</summary>
    public IReadOnlyList<string> ContentFields { get; init; } = Array.Empty<string>();
}

/// <summary>
/// Configuração completa de parsing.
/// </summary>
public record ParseConfig
{
    /// <summary>Estratégia de parsing.</summary>
    public ParseStrategy Strategy { get; init; } = ParseStrategy.CsvRowToDocument;
    
    /// <summary>Configuração específica de CSV.</summary>
    public CsvParseConfig? CsvConfig { get; init; }
    
    /// <summary>Mapeamento de campos.</summary>
    public IReadOnlyDictionary<string, FieldMapping> Fields { get; init; } = 
        new Dictionary<string, FieldMapping>();
    
    /// <summary>Campos de metadata (aninhados).</summary>
    public IReadOnlyDictionary<string, FieldMapping>? MetadataFields { get; init; }
    
    /// <summary>Composição do documento.</summary>
    public DocumentComposition? Document { get; init; }
}
