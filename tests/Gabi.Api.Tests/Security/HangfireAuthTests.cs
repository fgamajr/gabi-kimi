using System.Security.Claims;
using Gabi.Api;
using Microsoft.AspNetCore.Http;
using Xunit;

namespace Gabi.Api.Tests.Security;

public class HangfireAuthTests
{
    [Fact]
    public void Dashboard_AdminUser_AllowsAccess()
    {
        var context = CreateContext(isAuthenticated: true, role: "Admin");
        Assert.True(HangfireDashboardAuthFilter.IsAuthorized(context));
    }

    [Fact]
    public void Dashboard_OperatorUser_DeniesAccess()
    {
        var context = CreateContext(isAuthenticated: true, role: "Operator");
        Assert.False(HangfireDashboardAuthFilter.IsAuthorized(context));
    }

    [Fact]
    public void Dashboard_Unauthenticated_DeniesAccess()
    {
        var context = CreateContext(isAuthenticated: false, role: null);
        Assert.False(HangfireDashboardAuthFilter.IsAuthorized(context));
    }

    private static HttpContext CreateContext(bool isAuthenticated, string? role)
    {
        var context = new DefaultHttpContext();
        if (!isAuthenticated)
        {
            context.User = new ClaimsPrincipal(new ClaimsIdentity());
            return context;
        }

        var claims = new List<Claim> { new(ClaimTypes.Name, "tester") };
        if (!string.IsNullOrWhiteSpace(role))
            claims.Add(new Claim(ClaimTypes.Role, role));

        context.User = new ClaimsPrincipal(new ClaimsIdentity(claims, "test-auth"));
        return context;
    }
}
