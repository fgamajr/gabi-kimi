using System.Text;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.IdentityModel.Tokens;

namespace Gabi.Api.Configuration;

public static class SecurityConfig
{
    /// <summary>
    /// Configura autenticação JWT
    /// </summary>
    public static IServiceCollection AddJwtAuthentication(
        this IServiceCollection services, 
        IConfiguration configuration)
    {
        var jwtKey = configuration["Jwt:Key"] 
            ?? throw new InvalidOperationException("JWT Key not configured");
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
