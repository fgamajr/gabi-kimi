using System.Text.Json;
using Gabi.Contracts.Workflow;
using Gabi.Postgres.Entities;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Appends pipeline stage history events to workflow_events.
/// Best-effort: all exceptions are caught and logged — never rethrown.
/// </summary>
public class WorkflowEventRepository : IWorkflowEventRepository
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<WorkflowEventRepository> _logger;

    public WorkflowEventRepository(IServiceScopeFactory scopeFactory, ILogger<WorkflowEventRepository> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    public async Task EmitAsync(
        Guid correlationId,
        Guid jobId,
        string sourceId,
        string jobType,
        string eventType,
        IReadOnlyDictionary<string, object>? metadata,
        CancellationToken ct = default)
    {
        try
        {
            await using var scope = _scopeFactory.CreateAsyncScope();
            var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

            var entity = new WorkflowEventEntity
            {
                Id = Guid.NewGuid(),
                CorrelationId = correlationId,
                JobId = jobId,
                SourceId = sourceId,
                JobType = jobType,
                EventType = eventType,
                Metadata = metadata is { Count: > 0 } ? JsonSerializer.Serialize(metadata) : null,
                CreatedAt = DateTime.UtcNow
            };
            context.WorkflowEvents.Add(entity);
            await context.SaveChangesAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex,
                "WorkflowEventRepository.EmitAsync swallowed exception (best-effort) for job {JobId} event {EventType}",
                jobId, eventType);
        }
    }
}
