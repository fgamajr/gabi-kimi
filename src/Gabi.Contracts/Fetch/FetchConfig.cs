namespace Gabi.Contracts.Fetch;

/// <summary>
/// Protocolos HTTP suportados.
/// </summary>
public enum HttpProtocol
{
    Http,
    Https
}

/// <summary>
/// Formatos de saída do fetch.
/// </summary>
public enum FetchOutputFormat
{
    Binary,
    Text,
    Csv,
    Json,
    Xml
}

/// <summary>
/// Configuração de streaming.
/// </summary>
public record StreamingConfig
{
    /// <summary>Streaming habilitado.</summary>
    public bool Enabled { get; init; } = false;
    
    /// <summary>Tamanho do chunk em bytes.</summary>
    public int ChunkSize { get; init; } = 65536; // 64KB
    
    /// <summary>Tamanho da fila (número de chunks).</summary>
    public int QueueSize { get; init; } = 1000;
    
    /// <summary>Decodificar Unicode durante streaming.</summary>
    public bool DecodeUnicode { get; init; } = true;
}

/// <summary>
/// Limites de recursos para fetch.
/// </summary>
public record FetchLimits
{
    /// <summary>Tamanho máximo do arquivo (ex: "100MB", "1GB").</summary>
    public string MaxSize { get; init; } = "100MB";
    
    /// <summary>Timeout de conexão.</summary>
    public string ConnectTimeout { get; init; } = "30s";
    
    /// <summary>Timeout de leitura (null = sem timeout para streaming).</summary>
    public string? ReadTimeout { get; init; } = null;
}

/// <summary>
/// Configuração de formato CSV.
/// </summary>
public record CsvFormatConfig
{
    /// <summary>Encoding (ex: utf-8).</summary>
    public string Encoding { get; init; } = "utf-8";
    
    /// <summary>Delimitador.</summary>
    public string Delimiter { get; init; } = "|";
    
    /// <summary>Caractere de quote.</summary>
    public string QuoteChar { get; init; } = "\"";
    
    /// <summary>Caractere de escape.</summary>
    public string? EscapeChar { get; init; } = null;
    
    /// <summary>Duplicar quotes.</summary>
    public bool DoubleQuote { get; init; } = true;
    
    /// <summary>Pular espaço inicial.</summary>
    public bool SkipInitialSpace { get; init; } = true;
    
    /// <summary>Terminador de linha (auto = detectar).</summary>
    public string LineTerminator { get; init; } = "auto";
}

/// <summary>
/// Configuração de fetch.
/// </summary>
public record FetchConfig
{
    /// <summary>Protocolo HTTP.</summary>
    public HttpProtocol Protocol { get; init; } = HttpProtocol.Https;
    
    /// <summary>Método HTTP.</summary>
    public string Method { get; init; } = "GET";
    
    /// <summary>Headers HTTP adicionais.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; init; } = 
        new Dictionary<string, string>();
    
    /// <summary>Timeout da requisição.</summary>
    public string Timeout { get; init; } = "5m";
    
    /// <summary>Formato de saída.</summary>
    public FetchOutputFormat OutputFormat { get; init; } = FetchOutputFormat.Binary;
    
    /// <summary>Configuração de formato CSV (se aplicável).</summary>
    public CsvFormatConfig? CsvFormat { get; init; }
    
    /// <summary>Configuração de streaming.</summary>
    public StreamingConfig Streaming { get; init; } = new();
    
    /// <summary>Limites de recursos.</summary>
    public FetchLimits Limits { get; init; } = new();
}
