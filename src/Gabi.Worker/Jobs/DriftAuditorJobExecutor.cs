using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Worker.Projection;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Detects drift between PostgreSQL and Elasticsearch document counts per source.
/// Enqueues embed_and_index repair jobs when drift exceeds 1% threshold.
/// Defers when WAL projection is catching up (lag > 50 MB) — Invariant 4.
/// Runs hourly as a Hangfire recurring job ("drift_audit").
/// </summary>
public class DriftAuditorJobExecutor : IJobExecutor
{
    public string JobType => "drift_audit";

    private const double DriftThreshold = 0.01;
    private const int MaxPendingEmbed = 500;
    private const int RepairBatchSize = 200;

    private readonly GabiDbContext _context;
    private readonly IDocumentIndexer _indexer;
    private readonly IJobQueueRepository _jobQueue;
    private readonly ProjectionLagMonitor _lagMonitor;
    private readonly IConfiguration _configuration;
    private readonly ILogger<DriftAuditorJobExecutor> _logger;

    public DriftAuditorJobExecutor(
        GabiDbContext context,
        IDocumentIndexer indexer,
        IJobQueueRepository jobQueue,
        ProjectionLagMonitor lagMonitor,
        IConfiguration configuration,
        ILogger<DriftAuditorJobExecutor> logger)
    {
        _context = context;
        _indexer = indexer;
        _jobQueue = jobQueue;
        _lagMonitor = lagMonitor;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        // Invariant 4: defer when WAL projection is catching up
        var lagBytes = await _lagMonitor.GetLagBytesAsync(ct);
        if (_lagMonitor.IsCatchingUp(lagBytes))
        {
            _logger.LogInformation(
                "drift_audit_deferred_lag={LagBytes}: projection catching up, skipping repair enqueue",
                lagBytes);
            return new JobResult
            {
                Status = JobTerminalStatus.Inconclusive,
                Metadata = new Dictionary<string, object>
                {
                    ["reason"] = "projection_catching_up",
                    ["lag_bytes"] = lagBytes
                }
            };
        }

        // Only audit sources opted into WAL projection
        var walEnabled = _configuration.GetValue<bool>("Gabi:EnableWalProjection");
        if (!walEnabled)
        {
            _logger.LogDebug("drift_audit: WAL projection disabled globally; nothing to audit");
            return new JobResult { Status = JobTerminalStatus.Skipped };
        }

        var sources = await _context.SourceRegistries
            .AsNoTracking()
            .Where(s => s.UseWalProjection && s.Enabled)
            .ToListAsync(ct);

        var repairQueued = 0;
        var drifted = 0;

        foreach (var source in sources)
        {
            ct.ThrowIfCancellationRequested();

            var pgCount = await _context.Documents
                .CountAsync(d => d.SourceId == source.Id
                                 && (d.Status == "active" || d.Status == "pending_projection" || d.Status == "completed"), ct);

            var esCount = await _indexer.GetActiveDocumentCountAsync(source.Id, ct) ?? pgCount;

            var driftRatio = pgCount == 0 ? 0.0 : Math.Abs(pgCount - esCount) / (double)pgCount;

            _context.ReconciliationRecords.Add(new ReconciliationRecordEntity
            {
                Id = Guid.NewGuid(),
                RunId = job.Id,
                SourceId = source.Id,
                PgActiveCount = pgCount,
                IndexActiveCount = esCount,
                DriftRatio = driftRatio,
                Status = driftRatio > DriftThreshold ? "drifted" : "ok",
                ReconciledAt = DateTime.UtcNow
            });

            if (driftRatio > DriftThreshold)
            {
                drifted++;
                _logger.LogWarning(
                    "Drift detected for source {SourceId}: pg={PgCount}, es={EsCount}, ratio={Ratio:P2}",
                    source.Id, pgCount, esCount, driftRatio);

                // Check how many embed jobs are already pending to avoid overloading
                var pendingEmbedCount = await _context.JobRegistry
                    .CountAsync(r => r.SourceId == source.Id
                                     && r.JobType == "embed_and_index"
                                     && (r.Status == "pending" || r.Status == "processing"), ct);

                if (pendingEmbedCount >= MaxPendingEmbed)
                {
                    _logger.LogDebug(
                        "Skipping repair for {SourceId}: {PendingCount} embed jobs already pending",
                        source.Id, pendingEmbedCount);
                    continue;
                }

                // Find pending_projection documents that need repair
                var pendingRepair = await _context.Documents
                    .Where(d => d.SourceId == source.Id && d.Status == "pending_projection")
                    .Take(RepairBatchSize)
                    .Select(d => d.Id)
                    .ToListAsync(ct);

                if (pendingRepair.Count > 0)
                {
                    await _jobQueue.EnqueueAsync(new IngestJob
                    {
                        Id = Guid.NewGuid(),
                        SourceId = source.Id,
                        JobType = "embed_and_index",
                        Payload = new Dictionary<string, object>
                        {
                            ["document_ids"] = pendingRepair.Select(id => id.ToString()).Cast<object>().ToList(),
                            ["repair"] = true
                        }
                    }, ct);
                    repairQueued += pendingRepair.Count;
                }
            }
        }

        await _context.SaveChangesAsync(ct);

        _logger.LogInformation(
            "DriftAuditor completed: {SourceCount} sources audited, {Drifted} drifted, {RepairQueued} repair docs queued",
            sources.Count, drifted, repairQueued);

        return new JobResult
        {
            Status = JobTerminalStatus.Success,
            Metadata = new Dictionary<string, object>
            {
                ["sources_audited"] = sources.Count,
                ["sources_drifted"] = drifted,
                ["repair_docs_queued"] = repairQueued
            }
        };
    }
}
