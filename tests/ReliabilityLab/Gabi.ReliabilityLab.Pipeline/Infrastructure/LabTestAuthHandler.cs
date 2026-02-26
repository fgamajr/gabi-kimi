using System.Security.Claims;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Gabi.ReliabilityLab.Pipeline.Infrastructure;

internal sealed class LabTestAuthHandler : AuthenticationHandler<AuthenticationSchemeOptions>
{
    public const string SchemeName = "Test";

    public LabTestAuthHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger, UrlEncoder encoder)
        : base(options, logger, encoder) { }

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var role = Request.Headers.TryGetValue("X-Test-Role", out var r) ? r.ToString() : "Operator";
        var user = Request.Headers.TryGetValue("X-Test-User", out var u) ? u.ToString() : "test-user";
        var claims = new[] { new Claim(ClaimTypes.Name, user), new Claim(ClaimTypes.NameIdentifier, user), new Claim(ClaimTypes.Role, role) };
        var identity = new ClaimsIdentity(claims, SchemeName);
        var ticket = new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName);
        return Task.FromResult(AuthenticateResult.Success(ticket));
    }
}
