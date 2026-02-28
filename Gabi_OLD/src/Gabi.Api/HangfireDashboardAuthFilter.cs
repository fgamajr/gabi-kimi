using Hangfire.Dashboard;
using Microsoft.AspNetCore.Http;

namespace Gabi.Api;

/// <summary>
/// Restringe o dashboard Hangfire a usuários autenticados (mesma auth da API).
/// </summary>
public class HangfireDashboardAuthFilter : IDashboardAuthorizationFilter
{
    public bool Authorize(DashboardContext context)
    {
        var httpContext = context.GetHttpContext();
        return IsAuthorized(httpContext);
    }

    public static bool IsAuthorized(HttpContext httpContext)
    {
        return httpContext.User.Identity?.IsAuthenticated == true &&
               httpContext.User.IsInRole("Admin");
    }
}
