using Gabi.Contracts.Jobs;
using Temporalio.Workflows;

namespace Gabi.Worker.Temporal;

/// <summary>
/// Durable Temporal workflow that wraps a single pipeline stage execution.
/// Retry policy mirrors Hangfire's existing policy (3 attempts, 2/8/30s delays).
/// Supports Pause and Stop signals.
/// </summary>
[Workflow]
public class PipelineWorkflow
{
    private bool _paused;
    private bool _stopped;

    [WorkflowRun]
    public async Task<PipelineWorkflowResult> RunAsync(PipelineWorkflowInput input)
    {
        // Check stop signal before starting
        if (_stopped)
            return new PipelineWorkflowResult(JobTerminalStatus.Skipped, "Workflow stopped before activity start");

        // If paused, wait until unpaused or stopped
        if (_paused)
            await Workflow.WaitConditionAsync(() => !_paused || _stopped);

        if (_stopped)
            return new PipelineWorkflowResult(JobTerminalStatus.Skipped, "Workflow stopped during pause");

        var retryPolicy = new Temporalio.Common.RetryPolicy
        {
            MaximumAttempts = 3,
            InitialInterval = TimeSpan.FromSeconds(2),
            MaximumInterval = TimeSpan.FromSeconds(30),
            BackoffCoefficient = 4
        };

        var options = new ActivityOptions
        {
            StartToCloseTimeout = TimeSpan.FromHours(4),
            RetryPolicy = retryPolicy
        };

        try
        {
            var result = await Workflow.ExecuteActivityAsync(
                (PipelineActivities act) => act.RunJobAsync(input),
                options);
            return result;
        }
        catch (Exception ex)
        {
            return new PipelineWorkflowResult(JobTerminalStatus.Failed, ex.Message);
        }
    }

    [WorkflowSignal]
    public Task PauseAsync()
    {
        _paused = true;
        return Task.CompletedTask;
    }

    [WorkflowSignal]
    public Task StopAsync()
    {
        _stopped = true;
        _paused = false; // unblock any wait
        return Task.CompletedTask;
    }

    [WorkflowSignal]
    public Task ResumeAsync()
    {
        _paused = false;
        return Task.CompletedTask;
    }
}
