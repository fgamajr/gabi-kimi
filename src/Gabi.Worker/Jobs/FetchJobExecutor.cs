using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Fetch executor: processa fetch_items pending/failed para uma source e marca status por item.
/// Ao concluir um item, cria documento pending para a fase de ingest.
/// </summary>
public class FetchJobExecutor : IJobExecutor
{
    public string JobType => "fetch";

    private readonly GabiDbContext _context;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly ILogger<FetchJobExecutor> _logger;

    public FetchJobExecutor(
        GabiDbContext context,
        IFetchItemRepository fetchItemRepository,
        ILogger<FetchJobExecutor> logger)
    {
        _context = context;
        _fetchItemRepository = fetchItemRepository;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        var sourceId = job.SourceId;
        var startedAt = DateTime.UtcNow;
        var fetchRun = new FetchRunEntity
        {
            JobId = job.Id,
            SourceId = sourceId,
            StartedAt = startedAt,
            Status = "processing"
        };
        _context.FetchRuns.Add(fetchRun);
        await _context.SaveChangesAsync(ct);

        var candidates = await _fetchItemRepository.GetBySourceAndStatusesAsync(
            sourceId,
            limit: 5000,
            statuses: new[] { "pending", "failed" },
            ct);

        if (candidates.Count == 0)
        {
            fetchRun.CompletedAt = DateTime.UtcNow;
            fetchRun.Status = "completed";
            fetchRun.ItemsTotal = 0;
            fetchRun.ItemsCompleted = 0;
            fetchRun.ItemsFailed = 0;
            await _context.SaveChangesAsync(ct);
            progress.Report(new JobProgress { PercentComplete = 100, Message = "Nenhum fetch_item pendente", Metrics = new Dictionary<string, object>() });
            return new JobResult { Success = true };
        }

        var total = candidates.Count;
        var completed = 0;
        var failed = 0;

        for (var i = 0; i < candidates.Count; i++)
        {
            var item = candidates[i];
            try
            {
                item.Status = "processing";
                item.Attempts++;
                item.StartedAt = DateTime.UtcNow;
                item.FetchRunId = fetchRun.Id;
                await _context.SaveChangesAsync(ct);

                // Fase fetch real ainda não baixa conteúdo remoto aqui.
                // Este passo valida a cadeia e cria unidade de ingestão por item de fetch.
                item.Status = "completed";
                item.CompletedAt = DateTime.UtcNow;
                item.LastError = null;

                var hasDocument = await _context.Documents
                    .AnyAsync(d => d.FetchItemId == item.Id, ct);
                if (!hasDocument)
                {
                    _context.Documents.Add(new DocumentEntity
                    {
                        LinkId = item.DiscoveredLinkId,
                        FetchItemId = item.Id,
                        SourceId = item.SourceId,
                        ExternalId = $"fetch-item-{item.Id}",
                        SourceContentHash = item.UrlHash,
                        Title = item.Url,
                        ContentUrl = item.Url,
                        Status = "pending",
                        ProcessingStage = "fetch_completed",
                        Metadata = "{}"
                    });
                }

                await _context.DiscoveredLinks
                    .Where(l => l.Id == item.DiscoveredLinkId)
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(x => x.FetchStatus, "completed")
                        .SetProperty(x => x.IngestStatus, "pending")
                        .SetProperty(x => x.UpdatedAt, DateTime.UtcNow), ct);

                await _context.SaveChangesAsync(ct);
                completed++;
            }
            catch (Exception ex)
            {
                failed++;
                item.Status = "failed";
                item.LastError = ex.Message.Length > 2000 ? ex.Message[..2000] : ex.Message;
                item.CompletedAt = DateTime.UtcNow;
                await _context.SaveChangesAsync(ct);
            }

            var percent = (int)Math.Round(((i + 1) * 100.0) / total);
            progress.Report(new JobProgress
            {
                PercentComplete = percent,
                Message = $"Fetch {i + 1}/{total}",
                Metrics = new Dictionary<string, object>
                {
                    ["items_total"] = total,
                    ["items_completed"] = completed,
                    ["items_failed"] = failed
                }
            });
        }

        fetchRun.CompletedAt = DateTime.UtcNow;
        fetchRun.ItemsTotal = total;
        fetchRun.ItemsCompleted = completed;
        fetchRun.ItemsFailed = failed;
        fetchRun.Status = failed == 0 ? "completed" : (completed > 0 ? "partial" : "failed");
        fetchRun.ErrorSummary = failed == 0 ? null : $"{failed} item(ns) falharam";
        await _context.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Fetch finished for {SourceId}: total={Total}, completed={Completed}, failed={Failed}",
            sourceId, total, completed, failed);

        return new JobResult
        {
            Success = failed < total,
            Metadata = new Dictionary<string, object>
            {
                ["fetch_run_id"] = fetchRun.Id.ToString(),
                ["items_total"] = total,
                ["items_completed"] = completed,
                ["items_failed"] = failed
            },
            ErrorMessage = failed == 0 ? null : $"{failed} item(s) failed"
        };
    }
}

