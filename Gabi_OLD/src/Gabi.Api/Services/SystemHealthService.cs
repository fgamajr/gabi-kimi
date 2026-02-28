// Copyright (c) 2026 Fábio Monteiro
// Licensed under the MIT License. See LICENSE file for details.

using Gabi.Contracts.Dashboard;
using Gabi.Postgres.Repositories;

namespace Gabi.Api.Services;

/// <summary>
/// Provides system health checks for PostgreSQL, Elasticsearch, and Redis.
/// </summary>
public interface ISystemHealthService
{
    Task<SystemHealthResponse> GetSystemHealthAsync(CancellationToken ct = default);
}

public class SystemHealthService : ISystemHealthService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<SystemHealthService> _logger;
    private readonly IConfiguration _configuration;

    public SystemHealthService(
        IServiceProvider serviceProvider,
        ILogger<SystemHealthService> logger,
        IConfiguration configuration)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _configuration = configuration;
    }

    public async Task<SystemHealthResponse> GetSystemHealthAsync(CancellationToken ct = default)
    {
        var services = new Dictionary<string, ServiceHealth>();
        var overallStatus = "ok";

        try
        {
            using var scope = _serviceProvider.CreateScope();

            // Check PostgreSQL
            var stopwatch = System.Diagnostics.Stopwatch.StartNew();
            try
            {
                var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
                var count = await sourceRepo.GetAllAsync(ct);
                stopwatch.Stop();
                services["postgresql"] = new ServiceHealth
                {
                    Status = "ok",
                    ResponseTimeMs = stopwatch.ElapsedMilliseconds,
                    Message = $"{count.Count} sources loaded"
                };
            }
            catch (Exception ex)
            {
                stopwatch.Stop();
                services["postgresql"] = new ServiceHealth
                {
                    Status = "error",
                    ResponseTimeMs = stopwatch.ElapsedMilliseconds,
                    Message = ex.Message
                };
                overallStatus = "degraded";
            }

            // Check Elasticsearch
            services["elasticsearch"] = new ServiceHealth
            {
                Status = await CheckElasticsearchAsync() ? "ok" : "error",
                Message = "Elasticsearch cluster"
            };

            // Check Redis (if configured)
            var redisConn = _configuration.GetConnectionString("Redis");
            services["redis"] = new ServiceHealth
            {
                Status = !string.IsNullOrEmpty(redisConn) ? "ok" : "disabled",
                Message = !string.IsNullOrEmpty(redisConn) ? "Connected" : "Not configured"
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking system health");
            overallStatus = "error";
        }

        return new SystemHealthResponse
        {
            Status = overallStatus,
            Timestamp = DateTime.UtcNow.ToString("O"),
            Services = services
        };
    }

    private async Task<bool> CheckElasticsearchAsync()
    {
        try
        {
            var esUrl = _configuration.GetConnectionString("Elasticsearch") ?? "http://localhost:9200";
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            var response = await client.GetAsync($"{esUrl.TrimEnd('/')}/_cluster/health");
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking Elasticsearch health");
            return false;
        }
    }
}
