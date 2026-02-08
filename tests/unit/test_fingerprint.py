"""Testes unitários para o módulo fingerprint.

Testa as funcionalidades de fingerprinting incluindo:
- Determinismo (mesmo doc = mesmo hash)
- Unicidade (docs diferentes = hashes diferentes)
- Normalização de conteúdo
- Inclusão de metadados
"""

import pytest
from datetime import datetime, timezone

from gabi.pipeline.fingerprint import (
    Fingerprinter,
    FingerprinterConfig,
)
from gabi.pipeline.contracts import ParsedDocument, DocumentFingerprint


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def default_fingerprinter():
    """Cria um fingerprinter com configuração padrão."""
    return Fingerprinter()


@pytest.fixture
def fingerprinter_with_metadata():
    """Cria um fingerprinter que inclui metadados."""
    config = FingerprinterConfig(include_metadata=True)
    return Fingerprinter(config)


@pytest.fixture
def fingerprinter_no_normalization():
    """Cria um fingerprinter sem normalização."""
    config = FingerprinterConfig(
        normalize_case=False,
        normalize_whitespace=False,
    )
    return Fingerprinter(config)


@pytest.fixture
def sample_document():
    """Cria um documento parseado de exemplo."""
    return ParsedDocument(
        document_id="TCU-ACORDAO-1234-2024",
        source_id="tcu_acordaos",
        title="Acórdão 1234/2024",
        content="EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital.",
        content_preview="EMENTA: Licitação...",
        content_type="text/html",
        url="https://pesquisa.apps.tcu.gov.br/#/documento/acordao/TCU-ACORDAO-1234-2024",
        language="pt-BR",
        metadata={
            "year": 2024,
            "number": "1234",
            "relator": "Ministro Teste",
        },
        parsed_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def identical_document():
    """Cria um documento idêntico ao sample_document."""
    return ParsedDocument(
        document_id="TCU-ACORDAO-1234-2024",
        source_id="tcu_acordaos",
        title="Acórdão 1234/2024",
        content="EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital.",
        content_preview="EMENTA: Licitação...",
        content_type="text/html",
        url="https://pesquisa.apps.tcu.gov.br/#/documento/acordao/TCU-ACORDAO-1234-2024",
        language="pt-BR",
        metadata={
            "year": 2024,
            "number": "1234",
            "relator": "Ministro Teste",
        },
        parsed_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def different_document():
    """Cria um documento com conteúdo diferente."""
    return ParsedDocument(
        document_id="TCU-ACORDAO-5678-2024",
        source_id="tcu_acordaos",
        title="Acórdão 5678/2024",
        content="EMENTA: Responsabilidade. Dano ao erário. Falha na licitação.",
        content_preview="EMENTA: Responsabilidade...",
        content_type="text/html",
        url="https://pesquisa.apps.tcu.gov.br/#/documento/acordao/TCU-ACORDAO-5678-2024",
        language="pt-BR",
        metadata={
            "year": 2024,
            "number": "5678",
            "relator": "Ministro Outro",
        },
        parsed_at=datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
    )


# =============================================================================
# Testes de Determinismo
# =============================================================================

class TestFingerprintDeterminism:
    """Testes de determinismo do fingerprint."""
    
    def test_same_document_same_hash(self, default_fingerprinter, sample_document):
        """test_fingerprint_determinism: Mesmo documento deve gerar mesmo hash."""
        fp1 = default_fingerprinter.compute(sample_document)
        fp2 = default_fingerprinter.compute(sample_document)
        
        assert fp1.fingerprint == fp2.fingerprint
        assert fp1.algorithm == fp2.algorithm
    
    def test_identical_documents_same_hash(self, default_fingerprinter, sample_document, identical_document):
        """Documentos idênticos devem ter fingerprints iguais."""
        fp1 = default_fingerprinter.compute(sample_document)
        fp2 = default_fingerprinter.compute(identical_document)
        
        assert fp1.fingerprint == fp2.fingerprint
    
    def test_determinism_across_instances(self, sample_document):
        """Fingerprints devem ser consistentes entre instâncias diferentes."""
        fp1 = Fingerprinter().compute(sample_document)
        fp2 = Fingerprinter().compute(sample_document)
        
        assert fp1.fingerprint == fp2.fingerprint
    
    def test_determinism_with_normalization(self, default_fingerprinter):
        """Documentos com whitespace diferente devem ter mesmo hash após normalização."""
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="Hello   World",
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content="Hello World",
        )
        
        fp1 = default_fingerprinter.compute(doc1)
        fp2 = default_fingerprinter.compute(doc2)
        
        assert fp1.fingerprint == fp2.fingerprint


# =============================================================================
# Testes de Unicidade
# =============================================================================

class TestFingerprintUniqueness:
    """Testes de unicidade do fingerprint."""
    
    def test_different_documents_different_hashes(self, default_fingerprinter, sample_document, different_document):
        """test_fingerprint_uniqueness: Documentos diferentes devem gerar hashes diferentes."""
        fp1 = default_fingerprinter.compute(sample_document)
        fp2 = default_fingerprinter.compute(different_document)
        
        assert fp1.fingerprint != fp2.fingerprint
    
    def test_same_content_different_ids_same_hash(self, default_fingerprinter):
        """Documentos com mesmo conteúdo mas IDs diferentes devem ter mesmo hash."""
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="source-a",
            content="Conteúdo idêntico",
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="source-b",
            content="Conteúdo idêntico",
        )
        
        fp1 = default_fingerprinter.compute(doc1)
        fp2 = default_fingerprinter.compute(doc2)
        
        # Mesmo conteúdo deve gerar mesmo fingerprint
        assert fp1.fingerprint == fp2.fingerprint
    
    def test_content_variations_produce_different_hashes(self, default_fingerprinter):
        """Variações mínimas no conteúdo devem gerar hashes diferentes."""
        # Usar variações significativas que não serão normalizadas
        contents = [
            "EMENTA: Licitação. Pregão Eletrônico.",
            "EMENTA: Licitação. Pregão Eletrônico. Decisão.",
            "EMENTA: Responsabilidade. Dano ao erário.",
            "EMENTA: Licitação. Pregão Eletrônico. X",
        ]
        
        docs = [
            ParsedDocument(document_id=f"DOC-{i}", source_id="test", content=content)
            for i, content in enumerate(contents)
        ]
        
        fingerprints = [default_fingerprinter.compute(doc).fingerprint for doc in docs]
        
        # Todos os fingerprints devem ser únicos
        assert len(set(fingerprints)) == len(fingerprints)


# =============================================================================
# Testes de Tamanho do Hash
# =============================================================================

class TestFingerprintLength:
    """Testes do tamanho do fingerprint."""
    
    def test_sha256_length_64_chars(self, default_fingerprinter, sample_document):
        """test_fingerprint_length: SHA-256 deve ter exatamente 64 caracteres hex."""
        fp = default_fingerprinter.compute(sample_document)
        
        assert len(fp.fingerprint) == 64
        assert fp.algorithm == "sha256"
    
    def test_sha512_length_128_chars(self, sample_document):
        """SHA-512 deve ter exatamente 128 caracteres hex."""
        config = FingerprinterConfig(algorithm="sha512")
        fingerprinter = Fingerprinter(config)
        
        fp = fingerprinter.compute(sample_document)
        
        assert len(fp.fingerprint) == 128
        assert fp.algorithm == "sha512"
    
    def test_hexadecimal_characters_only(self, default_fingerprinter, sample_document):
        """Fingerprint deve conter apenas caracteres hexadecimais."""
        fp = default_fingerprinter.compute(sample_document)
        
        # Deve ser apenas caracteres hex (0-9, a-f)
        assert all(c in '0123456789abcdef' for c in fp.fingerprint)
    
    def test_length_consistency(self, default_fingerprinter):
        """Tamanho deve ser consistente para diferentes documentos."""
        for i in range(10):
            doc = ParsedDocument(
                document_id=f"DOC-{i}",
                source_id="test",
                content=f"Conteúdo variado {i}",
            )
            fp = default_fingerprinter.compute(doc)
            assert len(fp.fingerprint) == 64


# =============================================================================
# Testes de Normalização
# =============================================================================

class TestContentNormalization:
    """Testes de normalização de conteúdo."""
    
    def test_whitespace_normalization(self, default_fingerprinter):
        """test_content_normalization: Whitespace excessivo deve ser normalizado."""
        doc = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="  Hello    World  ",
        )
        
        fp = default_fingerprinter.compute(doc)
        
        # O componente deve indicar normalização
        assert "normalized_length" in fp.components
        assert int(fp.components["normalized_length"]) < len(doc.content)
    
    def test_case_normalization(self, default_fingerprinter):
        """Case deve ser normalizado para lowercase."""
        doc_lower = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="hello world",
        )
        doc_upper = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content="HELLO WORLD",
        )
        doc_mixed = ParsedDocument(
            document_id="DOC-003",
            source_id="test",
            content="Hello World",
        )
        
        fp1 = default_fingerprinter.compute(doc_lower)
        fp2 = default_fingerprinter.compute(doc_upper)
        fp3 = default_fingerprinter.compute(doc_mixed)
        
        # Todas devem gerar o mesmo hash após normalização
        assert fp1.fingerprint == fp2.fingerprint == fp3.fingerprint
    
    def test_tabs_and_newlines_normalization(self, default_fingerprinter):
        """Tabs e newlines devem ser normalizados para espaço."""
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="Hello\t\t\tWorld",
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content="Hello\n\nWorld",
        )
        doc3 = ParsedDocument(
            document_id="DOC-003",
            source_id="test",
            content="Hello World",
        )
        
        fp1 = default_fingerprinter.compute(doc1)
        fp2 = default_fingerprinter.compute(doc2)
        fp3 = default_fingerprinter.compute(doc3)
        
        # Todas devem gerar o mesmo hash após normalização
        assert fp1.fingerprint == fp2.fingerprint == fp3.fingerprint
    
    def test_no_normalization_respects_original(self, fingerprinter_no_normalization):
        """Sem normalização, case e whitespace devem ser preservados."""
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="Hello World",
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content="hello world",
        )
        
        fp1 = fingerprinter_no_normalization.compute(doc1)
        fp2 = fingerprinter_no_normalization.compute(doc2)
        
        # Devem gerar hashes diferentes sem normalização de case
        assert fp1.fingerprint != fp2.fingerprint


# =============================================================================
# Testes de Metadados
# =============================================================================

class TestMetadataInclusion:
    """Testes de inclusão de metadados no fingerprint."""
    
    def test_metadata_excluded_by_default(self, default_fingerprinter, sample_document):
        """test_metadata_inclusion: Metadados devem ser excluídos por padrão."""
        fp = default_fingerprinter.compute(sample_document)
        
        # Sem metadados, não deve ter metadata_hash nos componentes
        assert "metadata_hash" not in fp.components
    
    def test_metadata_inclusion_changes_hash(self, sample_document):
        """Incluir metadados deve alterar o fingerprint."""
        fp_without = Fingerprinter().compute(sample_document)
        
        config_with = FingerprinterConfig(include_metadata=True)
        fp_with = Fingerprinter(config_with).compute(sample_document)
        
        # Hashes devem ser diferentes
        assert fp_without.fingerprint != fp_with.fingerprint
    
    def test_metadata_included_when_configured(self, fingerprinter_with_metadata, sample_document):
        """Metadados devem ser incluídos quando configurado."""
        fp = fingerprinter_with_metadata.compute(sample_document)
        
        # Deve ter metadata_hash nos componentes
        assert "metadata_hash" in fp.components
        assert fp.components["metadata_hash"] != ""
    
    def test_different_metadata_produces_different_hashes(self, fingerprinter_with_metadata):
        """Metadados diferentes devem produzir fingerprints diferentes."""
        base_content = "Conteúdo idêntico"
        
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content=base_content,
            metadata={"year": 2024, "relator": "Ministro A"},
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content=base_content,
            metadata={"year": 2024, "relator": "Ministro B"},
        )
        
        fp1 = fingerprinter_with_metadata.compute(doc1)
        fp2 = fingerprinter_with_metadata.compute(doc2)
        
        # Hashes devem ser diferentes devido aos metadados
        assert fp1.fingerprint != fp2.fingerprint
    
    def test_same_metadata_same_hash(self, fingerprinter_with_metadata):
        """Mesmos metadados devem produzir mesmo fingerprint."""
        base_content = "Conteúdo idêntico"
        metadata = {"year": 2024, "relator": "Ministro Teste"}
        
        doc1 = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content=base_content,
            metadata=metadata,
        )
        doc2 = ParsedDocument(
            document_id="DOC-002",
            source_id="test",
            content=base_content,
            metadata=metadata.copy(),
        )
        
        fp1 = fingerprinter_with_metadata.compute(doc1)
        fp2 = fingerprinter_with_metadata.compute(doc2)
        
        # Hashes devem ser idênticos
        assert fp1.fingerprint == fp2.fingerprint
    
    def test_specific_metadata_keys(self, sample_document):
        """Deve permitir selecionar chaves específicas de metadados."""
        config = FingerprinterConfig(
            include_metadata=True,
            metadata_keys=["year"],  # Apenas 'year'
        )
        fingerprinter = Fingerprinter(config)
        
        doc = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="Test content",
            metadata={"year": 2024, "relator": "Ministro Teste"},
        )
        
        fp = fingerprinter.compute(doc)
        
        # Deve incluir metadados
        assert "metadata_hash" in fp.components


# =============================================================================
# Testes de Validação e Erros
# =============================================================================

class TestFingerprintValidation:
    """Testes de validação e tratamento de erros."""
    
    def test_empty_content_raises_error(self, default_fingerprinter):
        """Documento sem conteúdo deve lançar erro."""
        doc = ParsedDocument(
            document_id="DOC-001",
            source_id="test",
            content="",
        )
        
        with pytest.raises(ValueError, match="sem conteúdo"):
            default_fingerprinter.compute(doc)
    
    def test_unsupported_algorithm_raises_error(self):
        """Algoritmo não suportado deve lançar erro."""
        config = FingerprinterConfig(algorithm="invalid")
        
        with pytest.raises(ValueError, match="não suportado"):
            Fingerprinter(config)
    
    def test_supported_algorithms(self, sample_document):
        """Algoritmos suportados devem funcionar."""
        supported = ["sha256", "sha512", "sha1", "md5"]
        
        for algo in supported:
            config = FingerprinterConfig(algorithm=algo)
            fingerprinter = Fingerprinter(config)
            fp = fingerprinter.compute(sample_document)
            
            assert fp.algorithm == algo
            assert len(fp.fingerprint) > 0


# =============================================================================
# Testes de Métodos Auxiliares
# =============================================================================

class TestFingerprintUtilities:
    """Testes de métodos utilitários."""
    
    def test_compute_from_text(self, default_fingerprinter):
        """compute_from_text deve funcionar corretamente."""
        fp = default_fingerprinter.compute_from_text(
            text="Test content",
            document_id="DOC-001",
            source_id="test-source",
        )
        
        assert isinstance(fp, DocumentFingerprint)
        assert fp.document_id == "DOC-001"
        assert fp.source_id == "test-source"
        assert len(fp.fingerprint) == 64
    
    def test_compare_equal_fingerprints(self, default_fingerprinter, sample_document):
        """compare deve retornar True para fingerprints iguais."""
        fp1 = default_fingerprinter.compute(sample_document)
        fp2 = default_fingerprinter.compute(sample_document)
        
        assert default_fingerprinter.compare(fp1, fp2) is True
    
    def test_compare_different_fingerprints(self, default_fingerprinter, sample_document, different_document):
        """compare deve retornar False para fingerprints diferentes."""
        fp1 = default_fingerprinter.compute(sample_document)
        fp2 = default_fingerprinter.compute(different_document)
        
        assert default_fingerprinter.compare(fp1, fp2) is False
    
    def test_get_fingerprint_info(self, default_fingerprinter, sample_document):
        """get_fingerprint_info deve retornar informações completas."""
        fp = default_fingerprinter.compute(sample_document)
        info = default_fingerprinter.get_fingerprint_info(fp)
        
        assert "fingerprint" in info
        assert "algorithm" in info
        assert "document_id" in info
        assert "source_id" in info
        assert "components" in info
        assert "created_at" in info
        
        assert info["fingerprint"] == fp.fingerprint
        assert info["algorithm"] == fp.algorithm


# =============================================================================
# Testes de Componentes
# =============================================================================

class TestFingerprintComponents:
    """Testes dos componentes do fingerprint."""
    
    def test_content_hash_component(self, default_fingerprinter, sample_document):
        """Deve incluir content_hash nos componentes."""
        fp = default_fingerprinter.compute(sample_document)
        
        assert "content_hash" in fp.components
        assert "content_length" in fp.components
        assert len(fp.components["content_hash"]) == 64
    
    def test_content_length_tracking(self, default_fingerprinter, sample_document):
        """Deve rastrear tamanhos do conteúdo."""
        fp = default_fingerprinter.compute(sample_document)
        
        original_length = int(fp.components["content_length"])
        normalized_length = int(fp.components["normalized_length"])
        
        assert original_length == len(sample_document.content)
        assert normalized_length <= original_length
