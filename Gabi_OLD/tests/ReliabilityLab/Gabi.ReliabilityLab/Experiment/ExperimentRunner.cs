using System.Diagnostics;
using Gabi.ReliabilityLab.Determinism;
using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Policy;
using Gabi.ReliabilityLab.Reporting;
using Gabi.ReliabilityLab.Telemetry;
using Gabi.ReliabilityLab.Verification;
using Microsoft.Extensions.Logging;

namespace Gabi.ReliabilityLab.Experiment;

public sealed class ExperimentRunner
{
    private readonly IEnvironmentController _environment;
    private readonly ITelemetrySink _telemetry;
    private readonly IDiagnosticReporter _reporter;
    private readonly IClock _clock;
    private readonly ILogger _logger;
    private readonly TimeSpan _clockStabilizationDelay;

    public ExperimentRunner(
        IEnvironmentController environment,
        ITelemetrySink telemetry,
        IDiagnosticReporter reporter,
        IClock clock,
        ILogger logger,
        TimeSpan? clockStabilizationDelay = null)
    {
        _environment = environment;
        _telemetry = telemetry;
        _reporter = reporter;
        _clock = clock;
        _logger = logger;
        _clockStabilizationDelay = clockStabilizationDelay ?? TimeSpan.FromSeconds(2);
    }

    public async Task<(ExperimentResult Result, PolicyVerdict Verdict, string ArtifactPath)> RunAsync(
        IExperiment experiment,
        ExperimentDefinition definition,
        IReadOnlyList<IEvaluationPolicy> policies,
        string? artifactBasePath = null,
        CancellationToken ct = default)
    {
        var correlationId = $"{definition.Name}_{definition.RandomSeed}_{_clock.UtcNow:yyyyMMddHHmmss}";
        var random = new DeterministicRandom(definition.RandomSeed);

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutCts.CancelAfter(definition.Timeout);

        EnvironmentConnectionInfo connectionInfo;
        try
        {
            connectionInfo = await _environment.StartAsync(timeoutCts.Token).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Environment start failed");
            var failedResult = new ExperimentResult
            {
                ExperimentName = definition.Name,
                CorrelationId = correlationId,
                StartedAt = _clock.UtcNow,
                CompletedAt = _clock.UtcNow,
                Duration = TimeSpan.Zero,
                Crashed = true,
                ErrorSummary = ex.Message,
                Verifications = Array.Empty<VerificationResult>(),
                Resources = new ResourceMetrics(),
                Stages = Array.Empty<StageMetrics>(),
                Trace = new ExecutionTrace { CorrelationId = correlationId, Spans = Array.Empty<TraceSpan>() },
                RandomSeed = definition.RandomSeed
            };
            var verdict = PolicyEvaluator.EvaluateAll(failedResult, policies);
            return (failedResult, verdict, string.Empty);
        }

        await Task.Delay(_clockStabilizationDelay, timeoutCts.Token).ConfigureAwait(false);

        var baselineMemory = GetCurrentProcessMemoryMb();
        var startedAt = _clock.UtcNow;
        _telemetry.BeginCapture(correlationId);

        var context = new ExperimentContext
        {
            CorrelationId = correlationId,
            Clock = _clock,
            Random = random,
            Telemetry = _telemetry,
            Logger = _logger,
            Environment = connectionInfo,
            Definition = definition
        };

        var crashed = false;
        string? errorSummary = null;
        try
        {
            await experiment.ExecuteAsync(context, timeoutCts.Token).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            crashed = true;
            errorSummary = ex.Message;
            _logger.LogError(ex, "Experiment execution failed");
        }

        _telemetry.EndCapture();

        var verificationResults = await VerificationSuite.RunAllAsync(
            experiment.IntegrityChecks,
            experiment.SemanticChecks,
            experiment.ConsistencyChecks,
            connectionInfo,
            timeoutCts.Token).ConfigureAwait(false);

        var peakMemory = GetCurrentProcessMemoryMb();
        var completedAt = _clock.UtcNow;
        var duration = completedAt - startedAt;

        GC.Collect();
        GC.WaitForPendingFinalizers();
        var gen0 = GC.CollectionCount(0);
        var gen1 = GC.CollectionCount(1);
        var gen2 = GC.CollectionCount(2);

        _telemetry.RecordResourceMetrics(new ResourceMetrics
        {
            PeakMemoryMb = Math.Max(peakMemory, baselineMemory),
            Gen0Collections = gen0,
            Gen1Collections = gen1,
            Gen2Collections = gen2
        });

        var trace = _telemetry.GetTrace();
        var resources = _telemetry.GetResourceMetrics();
        var stages = _telemetry.GetStageMetrics();

        var result = new ExperimentResult
        {
            ExperimentName = definition.Name,
            CorrelationId = correlationId,
            StartedAt = startedAt,
            CompletedAt = completedAt,
            Duration = duration,
            Crashed = crashed,
            ErrorSummary = errorSummary,
            Verifications = verificationResults,
            Resources = resources,
            Stages = stages,
            Trace = trace,
            RandomSeed = definition.RandomSeed
        };

        var policyVerdict = PolicyEvaluator.EvaluateAll(result, policies);

        var root = artifactBasePath ?? Path.Combine(Directory.GetCurrentDirectory(), "artifacts", "reliability");
        var artifactDir = Path.Combine(root, $"{correlationId}");
        var artifactPath = await _reporter.GenerateAsync(artifactDir, result, policyVerdict, timeoutCts.Token).ConfigureAwait(false);

        try
        {
            await _environment.StopAsync(CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Environment stop failed");
        }

        return (result, policyVerdict, artifactPath);
    }

    private static double GetCurrentProcessMemoryMb()
    {
        using var proc = Process.GetCurrentProcess();
        return proc.WorkingSet64 / (1024.0 * 1024.0);
    }
}
