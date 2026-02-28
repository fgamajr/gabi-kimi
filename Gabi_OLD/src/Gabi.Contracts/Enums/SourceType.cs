namespace Gabi.Contracts.Enums;

/// <summary>
/// Tipos de fonte de dados.
/// </summary>
public enum SourceType
{
    Api,
    Web,
    File,
    Crawler
}

/// <summary>
/// Status de uma fonte.
/// </summary>
public enum SourceStatus
{
    Active,
    Paused,
    Error,
    Disabled
}

/// <summary>
/// Status de execução.
/// </summary>
public enum ExecutionStatus
{
    Pending,
    Running,
    Success,
    PartialSuccess,
    Failed,
    Cancelled
}

/// <summary>
/// Status de mensagem na DLQ.
/// </summary>
public enum DlqStatus
{
    Pending,
    Retrying,
    Exhausted,
    Resolved,
    Archived
}

/// <summary>
/// Nível de sensibilidade dos dados.
/// </summary>
public enum SensitivityLevel
{
    Public,
    Internal,
    Restricted,
    Confidential
}

/// <summary>
/// Tipo de busca.
/// </summary>
public enum SearchType
{
    Text,
    Semantic,
    Hybrid
}
