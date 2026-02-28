using Gabi.Contracts.Jobs;
using Xunit;

namespace Gabi.Jobs.Tests;

/// <summary>
/// Tests for JobStateMachine following TDD principles.
/// Red-Green-Refactor cycle.
/// </summary>
public class JobStateMachineTests
{
    private readonly JobStateMachine _stateMachine;

    public JobStateMachineTests()
    {
        _stateMachine = new JobStateMachine();
    }

    [Fact]
    public void TransitionAsync_PendingToRunning_WithWorkerId_UpdatesStatusAndStartedAt()
    {
        // Arrange
        var job = CreateTestJob(JobStatus.Pending);
        const string workerId = "worker-001";

        // Act
        var result = _stateMachine.TransitionAsync(job, JobStatus.Running, workerId, CancellationToken.None).Result;

        // Assert
        Assert.Equal(JobStatus.Running, result.Status);
        Assert.Equal(workerId, result.WorkerId);
        Assert.NotNull(result.StartedAt);
        Assert.True(result.StartedAt <= DateTime.UtcNow);
    }

    [Fact]
    public void TransitionAsync_RunningToCompleted_SetsCompletedAt()
    {
        // Arrange
        var job = CreateTestJob(JobStatus.Running);
        job = job with { 
            WorkerId = "worker-001",
            StartedAt = DateTime.UtcNow.AddMinutes(-1)
        };

        // Act
        var result = _stateMachine.TransitionAsync(job, JobStatus.Completed, null, CancellationToken.None).Result;

        // Assert
        Assert.Equal(JobStatus.Completed, result.Status);
        Assert.NotNull(result.CompletedAt);
        Assert.True(result.CompletedAt > result.StartedAt);
    }

    [Fact]
    public void TransitionAsync_RunningToFailed_SetsErrorMessage()
    {
        // Arrange
        var job = CreateTestJob(JobStatus.Running);
        const string errorMessage = "Connection timeout";

        // Act
        var result = _stateMachine.TransitionAsync(job, JobStatus.Failed, errorMessage, CancellationToken.None).Result;

        // Assert
        Assert.Equal(JobStatus.Failed, result.Status);
        Assert.Equal(errorMessage, result.ErrorMessage);
        Assert.NotNull(result.CompletedAt);
    }

    [Fact]
    public void TransitionAsync_InvalidTransition_ThrowsInvalidOperationException()
    {
        // Arrange - Cannot go from Pending directly to Completed
        var job = CreateTestJob(JobStatus.Pending);

        // Act & Assert
        var exception = Assert.Throws<InvalidOperationException>(() =>
            _stateMachine.TransitionAsync(job, JobStatus.Completed, null, CancellationToken.None).Result);
        
        Assert.Contains("Cannot transition", exception.Message);
    }

    [Fact]
    public void GetValidTransitions_Pending_ReturnsRunningAndSkipped()
    {
        // Act
        var transitions = _stateMachine.GetValidTransitions(JobStatus.Pending);

        // Assert
        Assert.Contains(JobStatus.Running, transitions);
        Assert.Contains(JobStatus.Skipped, transitions);
        Assert.DoesNotContain(JobStatus.Completed, transitions);
    }

    [Fact]
    public void GetValidTransitions_Running_ReturnsCompletedFailed()
    {
        // Act
        var transitions = _stateMachine.GetValidTransitions(JobStatus.Running);

        // Assert
        Assert.Contains(JobStatus.Completed, transitions);
        Assert.Contains(JobStatus.Failed, transitions);
        Assert.DoesNotContain(JobStatus.Pending, transitions);
    }

    [Fact]
    public void TransitionAsync_EmitsEvent_WhenTransitionOccurs()
    {
        // Arrange
        var job = CreateTestJob(JobStatus.Pending);
        JobTransitionEvent? capturedEvent = null;
        
        _stateMachine.OnTransition += (sender, e) => capturedEvent = e;

        // Act
        _stateMachine.TransitionAsync(job, JobStatus.Running, "worker-001", CancellationToken.None).Wait();

        // Assert
        Assert.NotNull(capturedEvent);
        Assert.Equal(JobStatus.Pending, capturedEvent.FromStatus);
        Assert.Equal(JobStatus.Running, capturedEvent.ToStatus);
        Assert.Equal(job.Id, capturedEvent.JobId);
    }

    [Fact]
    public void TransitionAsync_FailedToRetrying_IncrementsRetryCount()
    {
        // Arrange
        var job = CreateTestJob(JobStatus.Failed);
        job = job with { RetryCount = 1, MaxRetries = 3 };

        // Act
        var result = _stateMachine.TransitionAsync(job, JobStatus.Pending, null, CancellationToken.None).Result;

        // Assert
        Assert.Equal(JobStatus.Pending, result.Status);
        Assert.Equal(2, result.RetryCount);
        Assert.NotNull(result.RetryAt);
    }

    private static IngestJob CreateTestJob(JobStatus status)
    {
        return new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = "test-source",
            JobType = "test",
            Status = status,
            CreatedAt = DateTime.UtcNow.AddMinutes(-5),
            MaxRetries = 3
        };
    }
}


