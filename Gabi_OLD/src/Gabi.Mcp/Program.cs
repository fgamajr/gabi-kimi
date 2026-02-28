using Gabi.Mcp;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Http;
using Microsoft.Extensions.Logging;
using ModelContextProtocol.Server;

var builder = Host.CreateApplicationBuilder(args);

// MCP over stdio: Cursor reads stdout as JSON-RPC only. Send all logs to stderr.
builder.Logging.ClearProviders();
builder.Logging.AddConsole(options =>
{
    options.LogToStandardErrorThreshold = LogLevel.Trace;
});

builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?>
{
    ["GABI_API_URL"] = Environment.GetEnvironmentVariable("GABI_API_URL") ?? "http://localhost:5100",
});

builder.Services.AddHttpClient<GabiApiClient>((sp, client) =>
{
    var config = sp.GetRequiredService<IConfiguration>();
    var url = (config["GABI_API_URL"] ?? "http://localhost:5100").TrimEnd('/') + "/";
    client.BaseAddress = new Uri(url);
    client.Timeout = TimeSpan.FromSeconds(30);
});

builder.Services.AddMcpServer()
    .WithStdioServerTransport()
    .WithTools<GabiMcpTools>();

await builder.Build().RunAsync();
