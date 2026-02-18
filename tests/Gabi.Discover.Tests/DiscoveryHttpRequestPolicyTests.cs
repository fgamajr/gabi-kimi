using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Tests;

public class DiscoveryHttpRequestPolicyTests
{
    [Fact]
    public void FromConfig_WithUserAgentsFile_LoadsEntriesAndSkipsComments()
    {
        var filePath = Path.GetTempFileName();
        try
        {
            File.WriteAllText(filePath, """
                # comment
                Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36

                Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36
                """);

            using var doc = JsonDocument.Parse(JsonSerializer.Serialize(new
            {
                http = new
                {
                    user_agents_file = filePath,
                    user_agent_mode = "fixed"
                }
            }));

            var config = new DiscoveryConfig
            {
                Strategy = "web_crawl",
                Extra = doc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
            };

            var policy = DiscoveryHttpRequestPolicy.FromConfig(config);

            Assert.Equal("fixed", policy.UserAgentMode);
            Assert.Equal(2, policy.UserAgents.Count);
            Assert.Contains("Windows NT 10.0", policy.UserAgents[0]);
        }
        finally
        {
            if (File.Exists(filePath))
                File.Delete(filePath);
        }
    }

    [Fact]
    public void FromConfig_UsesEnvUserAgentsFile_WhenConfigDoesNotProvideAgents()
    {
        var filePath = Path.GetTempFileName();
        var oldValue = Environment.GetEnvironmentVariable("GABI_DISCOVERY_UA_FILE");
        try
        {
            File.WriteAllText(filePath, "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15");
            Environment.SetEnvironmentVariable("GABI_DISCOVERY_UA_FILE", filePath);

            var config = new DiscoveryConfig
            {
                Strategy = "api_pagination"
            };

            var policy = DiscoveryHttpRequestPolicy.FromConfig(config);

            Assert.Single(policy.UserAgents);
            Assert.Contains("Macintosh", policy.UserAgents[0]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("GABI_DISCOVERY_UA_FILE", oldValue);
            if (File.Exists(filePath))
                File.Delete(filePath);
        }
    }

    [Fact]
    public void FromConfig_ShouldReadRequestDelayMs_FromHttpNode()
    {
        using var doc = JsonDocument.Parse(JsonSerializer.Serialize(new
        {
            http = new
            {
                request_delay_ms = 1500,
                timeout = "180s"
            }
        }));

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = doc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var policy = DiscoveryHttpRequestPolicy.FromConfig(config);

        Assert.Equal(1500, policy.RequestDelayMs);
        Assert.Equal(TimeSpan.FromSeconds(180), policy.RequestTimeout);
    }
}
