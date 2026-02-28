using System.Reflection;
using NetArchTest.Rules;
using Xunit;

namespace Gabi.Architecture.Tests;

public class LayeringTests
{
    private static readonly Assembly[] GabiAssemblies = new[]
    {
        Assembly.Load("Gabi.Contracts"),
        Assembly.Load("Gabi.Discover"),
        Assembly.Load("Gabi.Fetch"),
        Assembly.Load("Gabi.Ingest"),
        Assembly.Load("Gabi.Sync"),
        Assembly.Load("Gabi.Jobs")
    };

    [Fact]
    public void ContractsLayer_ShouldNotReference_AnyOtherGabiProject()
    {
        var result = Types.InAssemblies(GabiAssemblies)
            .That().ResideInNamespace("Gabi.Contracts")
            .ShouldNot().HaveDependencyOnAny(
                "Gabi.Api", "Gabi.Worker", "Gabi.Discover",
                "Gabi.Fetch", "Gabi.Ingest", "Gabi.Postgres",
                "Gabi.Sync", "Gabi.Jobs")
            .GetResult();

        Assert.True(result.IsSuccessful,
            "Gabi.Contracts cannot reference other Gabi projects: " +
            string.Join(", ", result.FailingTypeNames ?? Array.Empty<string>()));
    }

    [Fact]
    public void DomainLayer_ShouldNotReference_Infrastructure()
    {
        var domainProjects = new[]
        {
            "Gabi.Discover", "Gabi.Fetch", "Gabi.Ingest",
            "Gabi.Sync", "Gabi.Jobs"
        };

        foreach (var project in domainProjects)
        {
            var result = Types.InAssemblies(GabiAssemblies)
                .That().ResideInNamespace(project)
                .ShouldNot().HaveDependencyOnAny(
                    "Gabi.Postgres",
                    "Microsoft.EntityFrameworkCore")
                .GetResult();

            Assert.True(result.IsSuccessful,
                $"{project} cannot reference infrastructure: " +
                string.Join(", ", result.FailingTypeNames ?? Array.Empty<string>()));
        }
    }

    [Fact]
    public void NoDuplicatedTypeNames_InDifferentNamespaces()
    {
        var contractsAssembly = typeof(Gabi.Contracts.Jobs.JobStatus).Assembly;

        var duplicates = contractsAssembly.GetTypes()
            .Where(t => t is { Name.Length: > 0, Namespace.Length: > 0 })
            .GroupBy(t => t.Name)
            .Where(g => g.Count() > 1 &&
                        g.Select(t => t.Namespace).Distinct().Count() > 1)
            .Select(g => g.Key)
            .OrderBy(name => name)
            .ToList();

        Assert.Empty(duplicates);
    }
}
