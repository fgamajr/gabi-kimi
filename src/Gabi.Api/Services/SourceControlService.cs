// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using System.Diagnostics;
using Gabi.Contracts.Common;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Api.Services;

/// <summary>
/// Provides operator pipeline control operations: pause, resume, and stop for a source.
/// </summary>
public interface ISourceControlService
{
    /// <summary>Pauses the pipeline for a source (running jobs will exit gracefully on next check).</summary>
    Task<RefreshSourceResponse> PauseSourceAsync(string sourceId, string? pausedBy = null, CancellationToken ct = default);

    /// <summary>Resumes the pipeline and optionally re-enqueues the active phase.</summary>
    Task<RefreshSourceResponse> ResumeSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>Stops the pipeline for a source (sets state to idle).</summary>
    Task<RefreshSourceResponse> StopSourceAsync(string sourceId, CancellationToken ct = default);
}

public class SourceControlService : ISourceControlService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<SourceControlService> _logger;

    public SourceControlService(
        IServiceProvider serviceProvider,
        ILogger<SourceControlService> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
    }

    public async Task<RefreshSourceResponse> PauseSourceAsync(string sourceId, string? pausedBy = null, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            return new RefreshSourceResponse { Success = false, Message = $"Source not found: {sourceId}" };

        var state = await db.SourcePipelineStates.FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        var now = DateTime.UtcNow;
        if (state == null)
        {
            db.SourcePipelineStates.Add(new SourcePipelineStateEntity
            {
                SourceId = sourceId,
                State = Status.Paused,
                PausedBy = pausedBy,
                PausedAt = now,
                UpdatedAt = now
            });
        }
        else
        {
            state.State = Status.Paused;
            state.PausedBy = pausedBy;
            state.PausedAt = now;
            state.UpdatedAt = now;
        }
        await db.SaveChangesAsync(ct);
        _logger.LogInformation("Pipeline paused for source {SourceId} by {PausedBy}", sourceId, pausedBy ?? "operator");
        return new RefreshSourceResponse { Success = true, Message = $"Pipeline paused for {sourceId}" };
    }

    public async Task<RefreshSourceResponse> ResumeSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            return new RefreshSourceResponse { Success = false, Message = $"Source not found: {sourceId}" };

        var state = await db.SourcePipelineStates.FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        var now = DateTime.UtcNow;
        if (state == null)
        {
            db.SourcePipelineStates.Add(new SourcePipelineStateEntity
            {
                SourceId = sourceId,
                State = Status.Running,
                LastResumedAt = now,
                UpdatedAt = now
            });
        }
        else
        {
            state.State = Status.Running;
            state.PausedBy = null;
            state.PausedAt = null;
            state.LastResumedAt = now;
            state.UpdatedAt = now;
        }
        await db.SaveChangesAsync(ct);

        var activePhase = state?.ActivePhase;
        if (!string.IsNullOrEmpty(activePhase) && activePhase is "discovery" or "fetch" or "ingest")
        {
            var latestJob = await jobQueue.GetLatestForSourceAsync(sourceId, ct);
            if (latestJob?.Status is not JobStatus.Running and not JobStatus.Pending)
            {
                var payload = BuildTraceContextPayload(new Dictionary<string, object> { ["phase"] = activePhase });
                var job = new IngestJob
                {
                    Id = Guid.NewGuid(),
                    JobType = activePhase == "discovery" ? "source_discovery" : activePhase,
                    SourceId = sourceId,
                    Payload = payload,
                    Status = JobStatus.Pending
                };
                await jobQueue.EnqueueAsync(job, ct);
                _logger.LogInformation("Resumed pipeline for {SourceId}: enqueued {Phase} job", sourceId, activePhase);
                return new RefreshSourceResponse { Success = true, JobId = job.Id, Message = $"Pipeline resumed and {activePhase} job enqueued for {sourceId}" };
            }
        }

        _logger.LogInformation("Pipeline resumed for source {SourceId}", sourceId);
        return new RefreshSourceResponse { Success = true, Message = $"Pipeline resumed for {sourceId}" };
    }

    public async Task<RefreshSourceResponse> StopSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            return new RefreshSourceResponse { Success = false, Message = $"Source not found: {sourceId}" };

        var state = await db.SourcePipelineStates.FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
        var now = DateTime.UtcNow;
        if (state == null)
        {
            db.SourcePipelineStates.Add(new SourcePipelineStateEntity
            {
                SourceId = sourceId,
                State = Status.Stopped,
                UpdatedAt = now
            });
        }
        else
        {
            state.State = Status.Stopped;
            state.ActivePhase = null;
            state.PausedBy = null;
            state.PausedAt = null;
            state.UpdatedAt = now;
        }
        await db.SaveChangesAsync(ct);
        _logger.LogInformation("Pipeline stopped for source {SourceId}", sourceId);
        return new RefreshSourceResponse { Success = true, Message = $"Pipeline stopped for {sourceId}" };
    }

    private static Dictionary<string, object> BuildTraceContextPayload(Dictionary<string, object> payload)
    {
        var traceParent = Activity.Current?.Id;
        var traceId = Activity.Current?.TraceId.ToString();

        if (!string.IsNullOrWhiteSpace(traceParent))
            payload["traceparent"] = traceParent;

        if (!string.IsNullOrWhiteSpace(traceId))
            payload["trace_id"] = traceId!;

        if (!payload.ContainsKey("request_id"))
            payload["request_id"] = traceId ?? Guid.NewGuid().ToString("N");

        return payload;
    }
}
