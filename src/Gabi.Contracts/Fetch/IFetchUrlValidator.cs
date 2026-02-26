namespace Gabi.Contracts.Fetch;

/// <summary>
/// Valida se uma URL pode ser usada pelo Worker para fetch (mitigação SSRF).
/// A implementação deve bloquear IPs de metadados, loopback e redes privadas,
/// e opcionalmente exigir allowlist de hosts/patterns.
/// </summary>
public interface IFetchUrlValidator
{
    /// <summary>
    /// Retorna true se a URL for permitida para requisição HTTP pelo Worker; false caso contrário.
    /// </summary>
    Task<bool> IsUrlAllowedAsync(string url, CancellationToken ct = default);
}
