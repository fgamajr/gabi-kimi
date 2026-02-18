using Gabi.Worker.Jobs;
using Hangfire;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Gabi.Postgres.Tests;

public class HangfireRetryPolicyTests
{
    [Fact]
    public void GabiJobRunner_RunAsync_ShouldNotUseMethodLevelAutomaticRetryAttribute()
    {
        var runMethod = typeof(GabiJobRunner).GetMethod(nameof(GabiJobRunner.RunAsync));

        Assert.NotNull(runMethod);
        var retryAttributes = runMethod!.GetCustomAttributes(typeof(AutomaticRetryAttribute), inherit: true);
        Assert.Empty(retryAttributes);
    }

    [Fact]
    public void HangfireRetryPolicyOptions_Defaults_ShouldMatchExpectedPolicy()
    {
        var options = new HangfireRetryPolicyOptions();

        Assert.Equal(3, options.Attempts);
        Assert.Equal(new[] { 2, 8, 30 }, options.DelaysInSeconds);
    }

    [Fact]
    public void DlqFilter_ShouldUseConfiguredRetryAttempts()
    {
        var serviceProvider = new ServiceCollection().BuildServiceProvider();
        var options = Options.Create(new HangfireRetryPolicyOptions { Attempts = 5, DelaysInSeconds = [1, 2, 3] });
        var filter = new DlqFilter(serviceProvider, NullLogger<DlqFilter>.Instance, options);

        var field = typeof(DlqFilter).GetField("_maxRetries", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
        Assert.NotNull(field);
        Assert.Equal(5, field!.GetValue(filter));
    }

}
