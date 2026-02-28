using Gabi.Contracts.Workflow;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Temporalio.Client;

namespace Gabi.Worker.Temporal;

/// <summary>
/// Checks Temporal reachability by attempting a brief connection.
/// Returns false on any exception — used by HangfireJobQueueRepository as a fail-closed guard.
/// </summary>
public class TemporalHealthCheck : ITemporalHealthCheck
{
    private readonly string _address;
    private readonly string _namespace;
    private readonly ILogger<TemporalHealthCheck> _logger;

    public TemporalHealthCheck(IConfiguration configuration, ILogger<TemporalHealthCheck> logger)
    {
        _address = configuration["Temporal:Address"] ?? "localhost:7233";
        _namespace = configuration["Temporal:Namespace"] ?? "default";
        _logger = logger;
    }

    public async Task<bool> IsReachableAsync(TimeSpan timeout, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);

        try
        {
            await TemporalClient.ConnectAsync(new TemporalClientConnectOptions(_address)
            {
                Namespace = _namespace
            });
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Temporal reachability check failed for {Address}", _address);
            return false;
        }
    }
}
