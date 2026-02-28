using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Configuration;

namespace Gabi.Mcp;

/// <summary>
/// HTTP client that calls the GABI API (search, documents, graph, dashboard).
/// Uses GABI_API_URL, GABI_API_TOKEN or GABI_API_USER/GABI_API_PASSWORD for auth.
/// </summary>
public sealed class GabiApiClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private string? _token;

    public GabiApiClient(HttpClient http, IConfiguration config)
    {
        _http = http;
        _baseUrl = (config["GABI_API_URL"] ?? "http://localhost:5100").TrimEnd('/');
        if (_http.BaseAddress == null)
            _http.BaseAddress = new Uri(_baseUrl + "/");
        _http.Timeout = TimeSpan.FromSeconds(30);
    }

    public async Task EnsureAuthAsync(CancellationToken ct = default)
    {
        if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("GABI_API_TOKEN")))
        {
            _token = Environment.GetEnvironmentVariable("GABI_API_TOKEN");
            return;
        }
        var user = Environment.GetEnvironmentVariable("GABI_API_USER") ?? "operator";
        var pwd = Environment.GetEnvironmentVariable("GABI_API_PASSWORD") ?? "op123";
        var login = await _http.PostAsJsonAsync("api/v1/auth/login", new { username = user, password = pwd }, ct);
        login.EnsureSuccessStatusCode();
        var json = await login.Content.ReadFromJsonAsync<JsonElement>(ct);
        _token = json.GetProperty("token").GetString();
    }

    private void SetAuth()
    {
        if (!string.IsNullOrEmpty(_token))
            _http.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _token);
    }

    public async Task<string> GetAsync(string path, CancellationToken ct = default)
    {
        await EnsureAuthAsync(ct);
        SetAuth();
        var resp = await _http.GetAsync(path, ct);
        resp.EnsureSuccessStatusCode();
        return await resp.Content.ReadAsStringAsync(ct);
    }

    public string BaseUrl => _baseUrl;
}
