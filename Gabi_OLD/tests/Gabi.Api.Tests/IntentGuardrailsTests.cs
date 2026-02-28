using Gabi.Api.Services;
using Xunit;

namespace Gabi.Api.Tests;

public class IntentGuardrailsTests
{
    [Fact]
    public void NormaVigente_ShouldAllowNormaNonRevogada()
    {
        var metadata = new Dictionary<string, object>
        {
            ["document_kind"] = "norma",
            ["normative_force"] = "desconhecido"
        };

        Assert.True(IntentGuardrails.Allows(IntentGuardrails.NormaVigente, metadata));
    }

    [Fact]
    public void NormaVigente_ShouldBlockProposicao()
    {
        var metadata = new Dictionary<string, object>
        {
            ["document_kind"] = "proposicao"
        };

        Assert.False(IntentGuardrails.Allows(IntentGuardrails.NormaVigente, metadata));
    }

    [Fact]
    public void NormaVigente_ShouldBlockRevogada()
    {
        var metadata = new Dictionary<string, object>
        {
            ["document_kind"] = "norma",
            ["normative_force"] = "revogada"
        };

        Assert.False(IntentGuardrails.Allows(IntentGuardrails.NormaVigente, metadata));
    }

    [Fact]
    public void ProposicaoIntent_ShouldAllowOnlyProposicao()
    {
        var norma = new Dictionary<string, object> { ["document_kind"] = "norma" };
        var proposicao = new Dictionary<string, object> { ["document_kind"] = "proposicao" };

        Assert.False(IntentGuardrails.Allows(IntentGuardrails.Proposicao, norma));
        Assert.True(IntentGuardrails.Allows(IntentGuardrails.Proposicao, proposicao));
    }
}
