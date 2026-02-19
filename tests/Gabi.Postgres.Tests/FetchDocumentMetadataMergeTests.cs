using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

public class FetchDocumentMetadataMergeTests
{
    [Fact]
    public void BuildDocumentMetadataJson_ShouldMergeLinkMetadataWithRowFields()
    {
        const string linkMetadata = """
            {
              "document_kind": "norma",
              "approval_state": "aprovada",
              "source_family": "senado_legislacao"
            }
            """;

        var rowFields = new Dictionary<string, string>
        {
            ["id"] = "123",
            ["titulo"] = "Norma de Teste"
        };

        var json = FetchJobExecutor.BuildDocumentMetadataJson(linkMetadata, rowFields);

        Assert.Contains("\"document_kind\":\"norma\"", json);
        Assert.Contains("\"approval_state\":\"aprovada\"", json);
        Assert.Contains("\"source_family\":\"senado_legislacao\"", json);
        Assert.Contains("\"id\":\"123\"", json);
        Assert.Contains("\"titulo\":\"Norma de Teste\"", json);
    }

    [Fact]
    public void BuildDocumentMetadataJson_WhenLinkMetadataInvalid_ShouldFallbackToRowFields()
    {
        var rowFields = new Dictionary<string, string>
        {
            ["id"] = "999",
            ["titulo"] = "Fallback"
        };

        var json = FetchJobExecutor.BuildDocumentMetadataJson("{not-json}", rowFields);

        Assert.DoesNotContain("document_kind", json);
        Assert.Contains("\"id\":\"999\"", json);
        Assert.Contains("\"titulo\":\"Fallback\"", json);
    }

    [Fact]
    public void DeriveNormativeForce_WhenComentarioContainsRevogacao_ShouldReturnRevogada()
    {
        var result = FetchJobExecutor.DeriveNormativeForce(["Declaração de Revogação total"]);
        Assert.Equal("revogada", result);
    }

    [Fact]
    public void DeriveNormativeForce_WhenComentarioContainsAlteracao_ShouldReturnModificada()
    {
        var result = FetchJobExecutor.DeriveNormativeForce(["Alteração Permanente do Art. 5"]);
        Assert.Equal("modificada", result);
    }

    [Fact]
    public void DeriveNormativeForce_WhenComentarioContainsAlteracaoProvisoria_ShouldReturnModificadaProvisoriamente()
    {
        var result = FetchJobExecutor.DeriveNormativeForce(["Declaração de Alteração Provisória"]);
        Assert.Equal("modificada_provisoriamente", result);
    }

    [Fact]
    public void DeriveNormativeForce_WhenNoRecognizedComentario_ShouldReturnDesconhecido()
    {
        var result = FetchJobExecutor.DeriveNormativeForce(["Declaração de referência cruzada"]);
        Assert.Equal("desconhecido", result);
    }
}
