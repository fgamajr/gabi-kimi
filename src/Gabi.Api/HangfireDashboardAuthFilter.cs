using Hangfire.Dashboard;

namespace Gabi.Api;

/// <summary>
/// Restringe o dashboard Hangfire a usuários autenticados (mesma auth da API).
/// </summary>
public class HangfireDashboardAuthFilter : IDashboardAuthorizationFilter
{
    public bool Authorize(DashboardContext context)
    {
        var httpContext = context.GetHttpContext();
        return httpContext.User.Identity?.IsAuthenticated == true;
    }
}
