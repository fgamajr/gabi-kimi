using Gabi.Api.Security;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Xunit;

namespace Gabi.Api.Tests.Security;

public class UserCredentialStoreSecurityTests
{
    [Fact]
    public void DevelopmentFallback_DoesNotLogPlaintextPasswords_AndRemainsUsable()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>())
            .Build();
        var logger = new ListLogger<UserCredentialStore>();
        var environment = new TestHostEnvironment(Environments.Development);

        var store = new UserCredentialStore(configuration, environment, logger);

        Assert.True(store.TryValidate("admin", "admin123", out var adminRole));
        Assert.Equal("Admin", adminRole);
        Assert.True(store.TryValidate("operator", "op123", out var operatorRole));
        Assert.Equal("Operator", operatorRole);
        Assert.True(store.TryValidate("viewer", "view123", out var viewerRole));
        Assert.Equal("Viewer", viewerRole);

        Assert.DoesNotContain(logger.Messages, m =>
            m.Contains("password=", StringComparison.OrdinalIgnoreCase) ||
            m.Contains("admin123", StringComparison.OrdinalIgnoreCase) ||
            m.Contains("op123", StringComparison.OrdinalIgnoreCase) ||
            m.Contains("view123", StringComparison.OrdinalIgnoreCase));
    }

    private sealed class TestHostEnvironment : IHostEnvironment
    {
        public TestHostEnvironment(string environmentName)
        {
            EnvironmentName = environmentName;
        }

        public string EnvironmentName { get; set; }
        public string ApplicationName { get; set; } = "Gabi.Api.Tests";
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
    }

    private sealed class ListLogger<T> : ILogger<T>
    {
        public List<string> Messages { get; } = new();

        IDisposable ILogger.BeginScope<TState>(TState state) => NullDisposable.Instance;

        bool ILogger.IsEnabled(LogLevel logLevel) => true;

        void ILogger.Log<TState>(
            LogLevel logLevel,
            EventId eventId,
            TState state,
            Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            Messages.Add(formatter(state, exception));
        }

        private sealed class NullDisposable : IDisposable
        {
            public static readonly NullDisposable Instance = new();
            public void Dispose()
            {
            }
        }
    }
}
