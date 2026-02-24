using FluentAssertions;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Worker.Jobs;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

public class GabiJobRunnerProgressTests
{
    [Fact]
    public async Task RunAsync_ShouldDrainProgressPump_AndPersistLastProgressMessage()
    {
        await using var sqlite = new SqliteConnection("Data Source=:memory:");
        await sqlite.OpenAsync();

        var services = new ServiceCollection();
        services.AddDbContext<GabiDbContext>(options => options.UseSqlite(sqlite));
        services.AddSingleton<IJobExecutor>(new ReportingExecutor("fetch"));
        var serviceProvider = services.BuildServiceProvider();

        var jobId = Guid.NewGuid();
        await using (var scope = serviceProvider.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            await db.Database.EnsureCreatedAsync();
            db.JobRegistry.Add(new JobRegistryEntity
            {
                JobId = jobId,
                SourceId = "source-progress",
                JobType = "fetch",
                Status = "pending",
                CreatedAt = DateTime.UtcNow
            });
            await db.SaveChangesAsync();
        }

        var loggerMock = new Mock<ILogger<GabiJobRunner>>();
        var runner = new GabiJobRunner(serviceProvider, loggerMock.Object);
        await runner.RunAsync(jobId, "fetch", "source-progress", "{}", CancellationToken.None);

        await using var assertScope = serviceProvider.CreateAsyncScope();
        var assertDb = assertScope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var reg = await assertDb.JobRegistry.SingleAsync(r => r.JobId == jobId);

        reg.Status.Should().Be("completed");
        reg.ProgressPercent.Should().Be(100);
        reg.ProgressMessage.Should().Be("step-2");
    }

    [Fact]
    public async Task RunAsync_ShouldLogWarning_WhenProgressArrivesAfterChannelClose()
    {
        var services = new ServiceCollection();
        services.AddDbContext<GabiDbContext>(options => options.UseInMemoryDatabase(Guid.NewGuid().ToString()));
        var lateProgressExecutor = new LateProgressExecutor("fetch");
        services.AddSingleton<IJobExecutor>(lateProgressExecutor);
        var serviceProvider = services.BuildServiceProvider();

        var jobId = Guid.NewGuid();
        await using (var scope = serviceProvider.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            db.JobRegistry.Add(new JobRegistryEntity
            {
                JobId = jobId,
                SourceId = "source-late-progress",
                JobType = "fetch",
                Status = "pending",
                CreatedAt = DateTime.UtcNow
            });
            await db.SaveChangesAsync();
        }

        var loggerMock = new Mock<ILogger<GabiJobRunner>>();
        var runner = new GabiJobRunner(serviceProvider, loggerMock.Object);
        await runner.RunAsync(jobId, "fetch", "source-late-progress", "{}", CancellationToken.None);

        await lateProgressExecutor.Reported.WaitAsync(TimeSpan.FromSeconds(3));

        loggerMock.Verify(
            x => x.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains("Dropped progress update")),
                It.IsAny<Exception>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtLeastOnce);
    }

    private sealed class ReportingExecutor(string jobType) : IJobExecutor
    {
        public string JobType { get; } = jobType;

        public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
        {
            progress.Report(new JobProgress { PercentComplete = 10, Message = "step-1" });
            progress.Report(new JobProgress { PercentComplete = 90, Message = "step-2" });
            await Task.Delay(100, CancellationToken.None);
            return new JobResult { Success = true };
        }
    }

    private sealed class LateProgressExecutor(string jobType) : IJobExecutor
    {
        private readonly TaskCompletionSource<bool> _reported = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public string JobType { get; } = jobType;
        public Task Reported => _reported.Task;

        public Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await Task.Delay(100, CancellationToken.None);
                    progress.Report(new JobProgress { PercentComplete = 50, Message = "late-update" });
                }
                finally
                {
                    _reported.TrySetResult(true);
                }
            }, CancellationToken.None);

            return Task.FromResult(new JobResult { Success = true });
        }
    }
}
