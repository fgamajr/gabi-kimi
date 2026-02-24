using System.Text;
using System.Threading.RateLimiting;
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
        this IServiceCollection services)
    {
        services.AddRateLimiter(options =>
        {
            // Fixed Window para endpoints de leitura
            options.AddFixedWindowLimiter("read", opt =>
            {
                opt.PermitLimit = 100;
                opt.Window = TimeSpan.FromMinutes(1);
                opt.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
                opt.QueueLimit = 10;
            });

            // Fixed Window mais restritivo para escrita
            options.AddFixedWindowLimiter("write", opt =>
            {
                opt.PermitLimit = 10;
                opt.Window = TimeSpan.FromMinutes(1);
                opt.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
                opt.QueueLimit = 2;
            });

            // Sliding Window para autenticação (login)
            options.AddSlidingWindowLimiter("auth", opt =>
            {
                opt.PermitLimit = 5;
                opt.Window = TimeSpan.FromMinutes(5);
                opt.SegmentsPerWindow = 5;
                opt.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
                opt.QueueLimit = 0;
            });

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
