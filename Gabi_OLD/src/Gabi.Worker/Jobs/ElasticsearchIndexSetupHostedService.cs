using Gabi.Ingest;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Garante que o índice ES existe com mapping correto no startup do Worker.
/// Registrado apenas quando Elasticsearch está configurado.
/// </summary>
public sealed class ElasticsearchIndexSetupHostedService : IHostedService
{
    private readonly ElasticsearchIndexSetup _setup;

    public ElasticsearchIndexSetupHostedService(ElasticsearchIndexSetup setup)
    {
        _setup = setup;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        await _setup.EnsureIndexExistsAsync(cancellationToken);
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
