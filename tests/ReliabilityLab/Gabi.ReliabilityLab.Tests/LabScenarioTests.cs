using FluentAssertions;
using Gabi.ReliabilityLab.Determinism;
using Gabi.ReliabilityLab.Experiment;
using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Policy;
using Gabi.ReliabilityLab.Reporting;
using Gabi.ReliabilityLab.Telemetry;
using Gabi.ReliabilityLab.Pipeline.Scenarios;
using Microsoft.Extensions.Logging;
using Xunit;

namespace Gabi.ReliabilityLab.Tests;

[Trait("Category", "ReliabilityLab")]
public sealed class LabScenarioTests
{
    [Fact]
    public async Task ZeroKelvin_Environment_StartsAndStops()
    {
        await using var env = new TestcontainersController();
        var info = await env.StartAsync();
        info.PostgreSqlConnectionString.Should().NotBeNullOrEmpty();
        info.RedisUrl.Should().NotBeNullOrEmpty();
        var snapshot = await env.GetReadinessAsync();
        snapshot.PostgreSql.Should().BeTrue();
        await env.StopAsync();
    }

    [Fact]
    public async Task ZeroKelvin_FullPipeline_MeetsPolicies()
    {
        await using var env = new TestcontainersController();
        var telemetry = new InMemoryTelemetrySink();
        var loggerFactory = LoggerFactory.Create(b => b.AddConsole().SetMinimumLevel(LogLevel.Warning));
        var reporter = new JsonDiagnosticReporter(loggerFactory.CreateLogger<JsonDiagnosticReporter>());
        var runner = new ExperimentRunner(env, telemetry, reporter, new SystemClock(), loggerFactory.CreateLogger("Lab"), TimeSpan.FromSeconds(1));

        var scenario = new ZeroKelvinScenario(new ZeroKelvinConfig
        {
            MaxDocs = 50,
            SourceId = "tcu_sumulas",
            PhaseTimeout = TimeSpan.FromMinutes(2),
            SampleSize = 20
        });

        var definition = new ExperimentDefinition
        {
            Name = "ZeroKelvin",
            RandomSeed = 42,
            Timeout = TimeSpan.FromMinutes(5)
        };

        var policies = new IEvaluationPolicy[]
        {
            new ReliabilityPolicy { MaxCrashCount = 0 },
            new DataQualityPolicy(),
            new PerformancePolicy { MaxMemoryMb = 500, MaxTotalDuration = TimeSpan.FromMinutes(10) }
        };

        var (result, verdict, artifactPath) = await runner.RunAsync(scenario, definition, policies);

        result.Crashed.Should().BeFalse(result.ErrorSummary ?? "no error");
        verdict.Passed.Should().BeTrue("violations: " + string.Join("; ", verdict.Violations.Select(v => v.Rule + "=" + v.ActualValue)));
        artifactPath.Should().NotBeNullOrEmpty();
    }
}
