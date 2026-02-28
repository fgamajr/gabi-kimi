using System.Text;
using System.Threading.RateLimiting;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.IdentityModel.Tokens;

namespace Gabi.Api.Configuration;

public static class SecurityConfig
{
    private const int MinJwtKeyLength = 32;
    private static readonly string[] DisallowedJwtKeyMarkers =
    [
        "sua-chave-super-secreta-com-minimo-32-caracteres!",
        "change-me",
        "dev-only"
    ];

    /// <summary>
    /// Configura autenticação JWT
    /// </summary>
    public static IServiceCollection AddJwtAuthentication(
        this IServiceCollection services, 
        IConfiguration configuration,
        IHostEnvironment environment)
    {
        var jwtKey = configuration["Jwt:Key"];
        if (string.IsNullOrWhiteSpace(jwtKey))
        {
            if (environment.IsEnvironment("Testing"))
                jwtKey = "testing-only-jwt-key-32-characters-minimum!";
            else
                throw new InvalidOperationException(
                    "Jwt:Key is required. Configure via environment variable Jwt__Key.");
        }

        ValidateJwtKey(jwtKey, environment);

        var jwtIssuer = configuration["Jwt:Issuer"] ?? "GabiApi";
        var jwtAudience = configuration["Jwt:Audience"] ?? "GabiDashboard";

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidateAudience = true,
                    ValidateLifetime = true,
                    ValidateIssuerSigningKey = true,
                    ValidIssuer = jwtIssuer,
                    ValidAudience = jwtAudience,
                    IssuerSigningKey = new SymmetricSecurityKey(
                        Encoding.UTF8.GetBytes(jwtKey)),
                    ClockSkew = TimeSpan.FromMinutes(5)
                };

                options.Events = new JwtBearerEvents
                {
                    OnAuthenticationFailed = context =>
                    {
                        // Log sem expor detalhes sensíveis
                        return Task.CompletedTask;
                    }
                };
            });

        return services;
    }

    private static void ValidateJwtKey(string jwtKey, IHostEnvironment environment)
    {
        if (string.IsNullOrWhiteSpace(jwtKey))
            throw new InvalidOperationException("Jwt:Key is required. Configure via environment variable Jwt__Key.");

        if (jwtKey.Length < MinJwtKeyLength)
            throw new InvalidOperationException($"Jwt:Key must contain at least {MinJwtKeyLength} characters.");

        if (environment.IsDevelopment() || environment.IsEnvironment("Testing"))
            return;

        var normalized = jwtKey.Trim();
        foreach (var marker in DisallowedJwtKeyMarkers)
        {
            if (normalized.Contains(marker, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    "Jwt:Key contains an insecure placeholder marker and is not allowed outside Development/Testing.");
            }
        }
    }

    /// <summary>
    /// Configura autorização com policies
    /// </summary>
    public static IServiceCollection AddAuthorizationPolicies(
        this IServiceCollection services)
    {
        services.AddAuthorization(options =>
        {
            options.AddPolicy("RequireAdmin", policy =>
                policy.RequireRole("Admin"));

            options.AddPolicy("RequireOperator", policy =>
                policy.RequireRole("Admin", "Operator"));

            options.AddPolicy("RequireViewer", policy =>
                policy.RequireRole("Admin", "Operator", "Viewer"));
        });

        return services;
    }

    /// <summary>
    /// Configura Rate Limiting
    /// </summary>
    public static IServiceCollection AddRateLimitingConfig(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        var readPermitLimit = GetPositiveInt(configuration, "Gabi:RateLimiting:Read:PermitLimit", 100);
        var readWindowSeconds = GetPositiveInt(configuration, "Gabi:RateLimiting:Read:WindowSeconds", 60);
        var readQueueLimit = GetNonNegativeInt(configuration, "Gabi:RateLimiting:Read:QueueLimit", 10);

        var writePermitLimit = GetPositiveInt(configuration, "Gabi:RateLimiting:Write:PermitLimit", 10);
        var writeWindowSeconds = GetPositiveInt(configuration, "Gabi:RateLimiting:Write:WindowSeconds", 60);
        var writeQueueLimit = GetNonNegativeInt(configuration, "Gabi:RateLimiting:Write:QueueLimit", 2);

        var authPermitLimit = GetPositiveInt(configuration, "Gabi:RateLimiting:Auth:PermitLimit", 5);
        var authWindowSeconds = GetPositiveInt(configuration, "Gabi:RateLimiting:Auth:WindowSeconds", 300);
        var authSegments = GetPositiveInt(configuration, "Gabi:RateLimiting:Auth:SegmentsPerWindow", 5);
        var authQueueLimit = GetNonNegativeInt(configuration, "Gabi:RateLimiting:Auth:QueueLimit", 0);

        services.AddRateLimiter(options =>
        {
            // Fixed Window para endpoints de leitura, particionado por usuário autenticado (fallback IP)
            options.AddPolicy("read", httpContext =>
                RateLimitPartition.GetFixedWindowLimiter(
                    partitionKey: BuildRateLimitPartitionKey(httpContext, "read", preferUserIdentity: true),
                    factory: _ => new FixedWindowRateLimiterOptions
                    {
                        PermitLimit = readPermitLimit,
                        Window = TimeSpan.FromSeconds(readWindowSeconds),
                        QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                        QueueLimit = readQueueLimit
                    }));

            // Fixed Window mais restritivo para escrita, particionado por usuário autenticado (fallback IP)
            options.AddPolicy("write", httpContext =>
                RateLimitPartition.GetFixedWindowLimiter(
                    partitionKey: BuildRateLimitPartitionKey(httpContext, "write", preferUserIdentity: true),
                    factory: _ => new FixedWindowRateLimiterOptions
                    {
                        PermitLimit = writePermitLimit,
                        Window = TimeSpan.FromSeconds(writeWindowSeconds),
                        QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                        QueueLimit = writeQueueLimit
                    }));

            // Sliding Window para autenticação (login), particionado por IP de origem
            options.AddPolicy("auth", httpContext =>
                RateLimitPartition.GetSlidingWindowLimiter(
                    partitionKey: BuildRateLimitPartitionKey(httpContext, "auth", preferUserIdentity: false),
                    factory: _ => new SlidingWindowRateLimiterOptions
                    {
                        PermitLimit = authPermitLimit,
                        Window = TimeSpan.FromSeconds(authWindowSeconds),
                        SegmentsPerWindow = authSegments,
                        QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                        QueueLimit = authQueueLimit
                    }));

            // Handler para rejeição
            options.OnRejected = async (context, token) =>
            {
                context.HttpContext.Response.StatusCode = StatusCodes.Status429TooManyRequests;
                context.HttpContext.Response.ContentType = "application/json";
                
                context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter);
                
                var message = new
                {
                    error = "Rate limit exceeded",
                    retryAfter = retryAfter.TotalSeconds
                };
                
                await context.HttpContext.Response.WriteAsJsonAsync(message, token);
            };
        });

        return services;
    }

    private static string BuildRateLimitPartitionKey(
        HttpContext context,
        string policyName,
        bool preferUserIdentity)
    {
        if (preferUserIdentity)
        {
            var userId =
                context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value ??
                context.User.FindFirst(ClaimTypes.Name)?.Value ??
                context.User.FindFirst("sub")?.Value;

            if (!string.IsNullOrWhiteSpace(userId))
                return $"{policyName}:user:{userId.Trim().ToLowerInvariant()}";
        }

        var remoteIp = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return $"{policyName}:ip:{remoteIp}";
    }

    private static int GetPositiveInt(IConfiguration configuration, string key, int fallback)
    {
        var value = configuration.GetValue<int?>(key);
        return value.HasValue && value.Value > 0 ? value.Value : fallback;
    }

    private static int GetNonNegativeInt(IConfiguration configuration, string key, int fallback)
    {
        var value = configuration.GetValue<int?>(key);
        return value.HasValue && value.Value >= 0 ? value.Value : fallback;
    }

    /// <summary>
    /// Configura CORS restritivo
    /// </summary>
    public static IServiceCollection AddCorsConfig(
        this IServiceCollection services, 
        IConfiguration configuration,
        IHostEnvironment environment)
    {
        var allowedOrigins = configuration.GetSection("Cors:AllowedOrigins")
            .Get<string[]>() ?? Array.Empty<string>();

        services.AddCors(options =>
        {
            options.AddPolicy("GabiCorsPolicy", policy =>
            {
                if (environment.IsDevelopment() && allowedOrigins.Length == 0)
                {
                    // Em dev, permitir localhost da API/UI local se não configurado
                    policy.WithOrigins(
                        "http://localhost:5173",
                        "http://localhost:4173"
                    );
                }
                else
                {
                    policy.WithOrigins(allowedOrigins);
                }

                policy
                    .AllowAnyMethod()
                    .AllowAnyHeader()
                    .AllowCredentials();
            });
        });

        return services;
    }
}
