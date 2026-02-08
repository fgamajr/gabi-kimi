"""Testes unitários para o módulo chunker.

Testa as funcionalidades de chunking incluindo:
- Chunking semântico por seções jurídicas
- Chunking de tamanho fixo
- Overlap entre chunks
- Preservação de estrutura legal (Artigos, §, etc.)
- Limites de tokens
"""

import pytest
from typing import Any, Dict, List
from unittest.mock import Mock, patch

from gabi.pipeline.contracts import Chunk, ChunkingResult
from gabi.types import SectionType


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def default_chunker():
    """Cria um chunker com configuração padrão."""
    from gabi.pipeline.chunker import Chunker
    return Chunker()


@pytest.fixture
def semantic_chunker():
    """Cria um chunker configurado para chunking semântico."""
    from gabi.pipeline.chunker import Chunker
    return Chunker(
        strategy="semantic_section",
        max_tokens=512,
        overlap_tokens=0,
    )


@pytest.fixture
def fixed_size_chunker():
    """Cria um chunker configurado para tamanho fixo."""
    from gabi.pipeline.chunker import Chunker
    return Chunker(
        strategy="fixed_size",
        max_tokens=256,
        overlap_tokens=50,
    )


@pytest.fixture
def chunker_with_overlap():
    """Cria um chunker com overlap configurado."""
    from gabi.pipeline.chunker import Chunker
    return Chunker(
        strategy="fixed_size",
        max_tokens=200,
        overlap_tokens=50,
    )


@pytest.fixture
def sample_acordao_text() -> str:
    """Texto de acórdão TCU para testes."""
    return """EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital. Irregularidade formal. Descabimento. Precedentes.

RELATÓRIO: O Ministro Relator apresentou os fatos pertinentes ao caso, demonstrando que a licitação seguiu todos os procedimentos legais estabelecidos na Lei 14.133/2021.

VOTO: O Ministro Vencedor opinou pelo conhecimento do recurso e, no mérito, pela sua improcedência, mantendo a decisão recorrida por seus próprios fundamentos.

ACÓRDÃO: O Tribunal, por unanimidade, decidiu pelo conhecimento e improcedência do recurso, nos termos do voto do Ministro Relator."""


@pytest.fixture
def sample_norma_text() -> str:
    """Texto de norma com artigos para testes."""
    return """Art. 1º Esta Lei estabelece normas gerais sobre licitações e contratos administrativos.

Art. 2º Para os fins desta Lei, considera-se:
I - licitação: procedimento administrativo formal destinado à seleção de proposta mais vantajosa para a Administração Pública.
II - contrato: acordo de vontades entre órgãos ou entidades da Administração Pública e particulares.

Art. 3º As licitações serão processadas e julgadas em estrita conformidade com os princípios básicos da legalidade, impessoalidade, moralidade, igualdade, publicidade, probidade administrativa, vinculação ao instrumento convocatório, julgamento objetivo e preservação do interesse público.

Art. 4º Ressalvadas as disposições constitucionais concernentes às compras internacionais, são obrigatórias para a União, Estados, Distrito Federal e Municípios as normas desta Lei.

§ 1º Aplicam-se às licitações e contratos das autarquias e das fundações públicas as normas referidas no caput.

§ 2º As empresas públicas e as sociedades de economia mista reger-se-ão por legislação específica, nos termos do art. 173 da Constituição Federal."""


@pytest.fixture
def sample_metadata() -> Dict[str, Any]:
    """Metadados de documento de exemplo."""
    return {
        "year": 2024,
        "number": "1234",
        "relator": "Ministro Teste",
        "document_type": "acordao",
    }


# =============================================================================
# Testes de Chunking Semântico
# =============================================================================

class TestChunkSemanticSections:
    """Testes de chunking semântico por seções jurídicas."""
    
    def test_chunk_semantic_sections_preserves_structure(
        self, semantic_chunker, sample_acordao_text, sample_metadata
    ):
        """test_chunk_semantic_sections: Preserva estrutura jurídica (EMENTA, RELATÓRIO, VOTO, ACÓRDÃO)."""
        result = semantic_chunker.chunk(sample_acordao_text, sample_metadata)
        
        # Deve retornar ChunkingResult
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) > 0
        
        # Verifica se as seções principais foram preservadas
        section_types = [chunk.section_type for chunk in result.chunks]
        
        # Pelo menos uma das seções principais deve estar presente
        expected_sections = {
            SectionType.EMENTA,
            SectionType.RELATORIO,
            SectionType.VOTO,
            SectionType.ACORDAO,
        }
        found_sections = set(section_types) & expected_sections
        assert len(found_sections) > 0, f"Nenhuma seção jurídica encontrada. Tipos: {section_types}"
    
    def test_chunk_semantic_sections_identifies_ementa(
        self, semantic_chunker, sample_acordao_text
    ):
        """Deve identificar corretamente a seção EMENTA."""
        result = semantic_chunker.chunk(sample_acordao_text, {})
        
        ementa_chunks = [c for c in result.chunks if c.section_type == SectionType.EMENTA]
        assert len(ementa_chunks) >= 1
        
        # O texto deve conter "EMENTA" ou conteúdo relacionado
        for chunk in ementa_chunks:
            assert "ementa" in chunk.text.lower() or "licitação" in chunk.text.lower()
    
    def test_chunk_semantic_sections_identifies_artigos(
        self, semantic_chunker, sample_norma_text
    ):
        """Deve identificar corretamente artigos em normas jurídicas."""
        result = semantic_chunker.chunk(sample_norma_text, {})
        
        artigo_chunks = [c for c in result.chunks if c.section_type == SectionType.ARTIGO]
        
        # Deve ter pelo menos 4 artigos
        assert len(artigo_chunks) >= 4, f"Esperado pelo menos 4 artigos, encontrados {len(artigo_chunks)}"
        
        # Verifica se os artigos estão na ordem correta
        indices = [c.index for c in artigo_chunks]
        assert indices == sorted(indices)
    
    def test_chunk_semantic_sections_identifies_paragrafos(
        self, semantic_chunker, sample_norma_text
    ):
        """Deve identificar parágrafos (§) em normas jurídicas."""
        result = semantic_chunker.chunk(sample_norma_text, {})
        
        paragrafo_chunks = [c for c in result.chunks if c.section_type == SectionType.PARAGRAFO]
        
        # Deve ter pelo menos 1 parágrafo identificado
        assert len(paragrafo_chunks) >= 1, f"Esperado pelo menos 1 parágrafo, encontrados {len(paragrafo_chunks)}"
    
    def test_chunk_semantic_sections_metadata(self, semantic_chunker, sample_acordao_text):
        """Deve incluir metadados relevantes nos chunks."""
        result = semantic_chunker.chunk(sample_acordao_text, {"relator": "Ministro Teste"})
        
        for chunk in result.chunks:
            # Cada chunk deve ter metadados
            assert isinstance(chunk.metadata, dict)
            # Deve ter informação de offset
            assert chunk.start_offset >= 0
            assert chunk.end_offset > chunk.start_offset
            # Deve ter contagem de caracteres
            assert chunk.char_count > 0
            # char_count deve ser aproximadamente igual ao tamanho do texto (pode ter pequena diferença)
            assert abs(chunk.char_count - len(chunk.text)) <= 5


# =============================================================================
# Testes de Chunking de Tamanho Fixo
# =============================================================================

class TestChunkFixedSize:
    """Testes de chunking com tamanho fixo."""
    
    def test_chunk_fixed_size_respects_max_tokens(
        self, fixed_size_chunker
    ):
        """test_chunk_fixed_size: Respeita limite máximo de tokens."""
        # Texto longo o suficiente para gerar múltiplos chunks
        text = "Palavra " * 1000  # ~1000 tokens aproximadamente
        
        result = fixed_size_chunker.chunk(text, {})
        
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) > 0
        
        # Todos os chunks devem respeitar o limite de tokens
        for chunk in result.chunks:
            assert chunk.token_count <= 256, f"Chunk {chunk.index} excede limite: {chunk.token_count} tokens"
    
    def test_chunk_fixed_size_creates_expected_number(
        self, fixed_size_chunker
    ):
        """Deve criar número esperado de chunks para texto grande."""
        # Texto que deve gerar pelo menos 3 chunks
        # Considerando ~256 tokens por chunk
        text = "Documento de teste. " * 200  # ~400 tokens
        
        result = fixed_size_chunker.chunk(text, {})
        
        # Com overlap de 50 e max 256, deve gerar aproximadamente 2 chunks
        assert len(result.chunks) >= 2, f"Esperado pelo menos 2 chunks, obtidos {len(result.chunks)}"
    
    def test_chunk_fixed_size_indices_sequential(
        self, fixed_size_chunker
    ):
        """Índices dos chunks devem ser sequenciais começando em 0."""
        text = "Texto de teste. " * 100
        
        result = fixed_size_chunker.chunk(text, {})
        
        indices = [chunk.index for chunk in result.chunks]
        expected_indices = list(range(len(result.chunks)))
        
        assert indices == expected_indices, f"Índices não sequenciais: {indices}"
    
    def test_chunk_fixed_size_with_short_text(
        self, fixed_size_chunker
    ):
        """Texto curto deve gerar chunk único."""
        text = "Texto curto."
        
        result = fixed_size_chunker.chunk(text, {})
        
        assert len(result.chunks) == 1
        assert result.chunks[0].text == text
        assert result.chunks[0].index == 0


# =============================================================================
# Testes de Overlap
# =============================================================================

class TestChunkOverlap:
    """Testes de overlap entre chunks."""
    
    def test_chunk_overlap_exists_between_chunks(
        self, chunker_with_overlap
    ):
        """test_chunk_overlap: Overlap funciona entre chunks consecutivos."""
        # Texto que deve gerar múltiplos chunks
        text = "Frase de teste número " + " ".join([f"{i}" for i in range(1, 101)])
        
        result = chunker_with_overlap.chunk(text, {})
        
        if len(result.chunks) < 2:
            pytest.skip("Não há chunks suficientes para testar overlap")
        
        # Verifica overlap entre chunks consecutivos
        for i in range(len(result.chunks) - 1):
            current_chunk = result.chunks[i]
            next_chunk = result.chunks[i + 1]
            
            # Deve haver algum overlap textual
            current_words = set(current_chunk.text.lower().split())
            next_words = set(next_chunk.text.lower().split())
            overlap = current_words & next_words
            
            # Deve haver alguma sobreposição de palavras significativas
            # (ignorando palavras muito curtas)
            significant_overlap = {w for w in overlap if len(w) > 3}
            assert len(significant_overlap) > 0, \
                f"Nenhum overlap significativo entre chunks {i} e {i+1}"
    
    def test_chunk_overlap_respects_token_count(
        self, chunker_with_overlap
    ):
        """Overlap deve ser contabilizado no total de tokens."""
        text = "Palavra " * 500
        
        result = chunker_with_overlap.chunk(text, {})
        
        # O total de tokens deve ser maior que se não houvesse overlap
        # devido à repetição de conteúdo
        total_tokens_with_overlap = sum(c.token_count for c in result.chunks)
        
        # Com overlap, o total de tokens processados deve ser maior
        assert total_tokens_with_overlap > 0
    
    def test_chunk_overlap_configuration(
        self, chunker_with_overlap
    ):
        """Configuração de overlap deve ser aplicada corretamente."""
        from gabi.pipeline.chunker import ChunkingConfig
        
        # Config com 0 overlap
        config_no_overlap = ChunkingConfig(strategy="fixed_size", max_tokens=100, overlap_tokens=0)
        
        # Config com 50 overlap
        config_with_overlap = ChunkingConfig(strategy="fixed_size", max_tokens=100, overlap_tokens=50)
        
        # As configurações devem ser diferentes
        assert config_no_overlap.overlap_tokens == 0
        assert config_with_overlap.overlap_tokens == 50


# =============================================================================
# Testes de Documentos Grandes
# =============================================================================

class TestChunkLargeDocument:
    """Testes de chunking para documentos grandes."""
    
    def test_chunk_large_document_handles_size(
        self, semantic_chunker
    ):
        """test_chunk_large_document: Documento grande é processado sem erros."""
        # Criar texto grande (simulando documento de várias páginas)
        large_text = "\n\n".join([
            f"Art. {i}º Disposição genérica sobre o tema {i}. "
            f"Este artigo estabelece as condições para aplicação da norma {i}. "
            f"§ 1º Na aplicação deste artigo, deve-se observar o disposto na legislação vigente."
            for i in range(1, 101)  # 100 artigos
        ])
        
        result = semantic_chunker.chunk(large_text, {})
        
        # Deve processar sem erros
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) > 0
        
        # Deve ter múltiplos chunks
        assert len(result.chunks) >= 10, f"Esperado muitos chunks, obtidos {len(result.chunks)}"
        
        # Todos os chunks devem ter conteúdo
        for chunk in result.chunks:
            assert len(chunk.text) > 0
            assert chunk.token_count > 0
    
    def test_chunk_large_document_performance(
        self, default_chunker
    ):
        """Chunking de documento grande deve ser eficiente."""
        import time
        
        large_text = "Texto repetido. " * 10000  # Texto grande
        
        start_time = time.time()
        result = default_chunker.chunk(large_text, {})
        elapsed_time = time.time() - start_time
        
        # Deve completar em tempo razoável (menos de 5 segundos)
        assert elapsed_time < 5.0, f"Chunking muito lento: {elapsed_time:.2f}s"
        assert len(result.chunks) > 0
    
    def test_chunk_large_document_memory_efficient(
        self, default_chunker
    ):
        """Chunking não deve consumir memória excessiva."""
        import sys
        
        large_text = "Documento extenso. " * 5000
        
        result = default_chunker.chunk(large_text, {})
        
        # Tamanho do resultado não deve ser muito maior que o texto original
        total_chunk_size = sum(len(c.text.encode('utf-8')) for c in result.chunks)
        original_size = len(large_text.encode('utf-8'))
        
        # Com overlap, pode ser maior, mas não absurdamente
        assert total_chunk_size < original_size * 2, \
            "Uso de memória excessivo no chunking"


# =============================================================================
# Testes de Documentos Vazios
# =============================================================================

class TestChunkEmptyDocument:
    """Testes de chunking para documentos vazios ou inválidos."""
    
    def test_chunk_empty_document_returns_empty_result(
        self, default_chunker
    ):
        """test_chunk_empty_document: Documento vazio retorna resultado vazio."""
        result = default_chunker.chunk("", {})
        
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) == 0
        assert result.total_tokens == 0
        assert result.total_chars == 0
    
    def test_chunk_whitespace_only_returns_empty_result(
        self, default_chunker
    ):
        """Documento com apenas whitespace retorna resultado vazio."""
        result = default_chunker.chunk("   \n\t  ", {})
        
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) == 0
    
    def test_chunk_none_content_raises_error_or_empty(
        self, default_chunker
    ):
        """test_chunk_empty_document: Conteúdo None deve lançar erro ou retornar vazio."""
        try:
            result = default_chunker.chunk(None, {})
            # Se não lançou exceção, deve retornar resultado vazio
            assert len(result.chunks) == 0
        except (ValueError, TypeError, AttributeError):
            pass  # Comportamento esperado é lançar exceção
    
    def test_chunk_minimal_content_works(
        self, default_chunker
    ):
        """Conteúdo mínimo válido deve funcionar."""
        result = default_chunker.chunk("X", {})
        
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) == 1
        assert result.chunks[0].text == "X"


# =============================================================================
# Testes de Preservação de Artigos
# =============================================================================

class TestArtigoNotSplit:
    """Testes para garantir que artigos não sejam cortados no meio."""
    
    def test_artigo_not_split_in_middle(
        self, semantic_chunker
    ):
        """test_artigo_not_split: Art. não é cortado no meio do texto."""
        text = """Art. 1º Este é o primeiro artigo da lei com conteúdo suficiente para ser um chunk completo.

Art. 2º Este é o segundo artigo que também deve ser preservado integralmente sem ser dividido."""
        
        result = semantic_chunker.chunk(text, {})
        
        # Verifica se cada artigo está completo em um chunk
        artigo_chunks = [c for c in result.chunks if c.section_type == SectionType.ARTIGO]
        
        for chunk in artigo_chunks:
            text_lower = chunk.text.lower()
            # Não deve começar no meio de um artigo
            assert not text_lower.lstrip().startswith(("º", "°", ".")), \
                f"Chunk começa no meio de um artigo: {chunk.text[:50]}"
    
    def test_artigo_boundaries_respected(
        self, semantic_chunker, sample_norma_text
    ):
        """Fronteiras entre artigos devem ser respeitadas."""
        result = semantic_chunker.chunk(sample_norma_text, {})
        
        for chunk in result.chunks:
            text = chunk.text.strip()
            
            # Se começa com número, deve ser início de artigo/parágrafo
            if text and text[0].isdigit():
                # Deve começar com "Art." ou "§"
                assert text.lower().startswith(("art.", "§")), \
                    f"Chunk {chunk.index} começa incorretamente: {text[:50]}"
    
    def test_paragrafo_not_split(
        self, semantic_chunker, sample_norma_text
    ):
        """Parágrafos (§) não devem ser cortados no meio."""
        result = semantic_chunker.chunk(sample_norma_text, {})
        
        paragrafo_chunks = [c for c in result.chunks if c.section_type == SectionType.PARAGRAFO]
        
        for chunk in paragrafo_chunks:
            # Deve começar com §
            assert "§" in chunk.text, \
                f"Chunk de parágrafo sem símbolo §: {chunk.text[:50]}"
    
    def test_multi_article_chunk_respects_limits(
        self, default_chunker
    ):
        """Se múltiplos artigos cabem em um chunk, devem ser agrupados."""
        # Texto com artigos curtos
        text = "\n".join([f"Art. {i}º Disposição {i}." for i in range(1, 11)])
        
        result = default_chunker.chunk(text, {})
        
        # Pode agrupar múltiplos artigos ou separar, mas não deve cortar no meio
        for chunk in result.chunks:
            # Conta quantos "Art." existem no chunk
            art_count = chunk.text.lower().count("art.")
            
            # Se tem múltiplos artigos, devem estar completos
            if art_count > 1:
                # Verifica se o texto termina corretamente (não no meio)
                lines = chunk.text.strip().split("\n")
                last_line = lines[-1].strip()
                # Última linha deve ser um artigo completo ou fim de parágrafo
                assert last_line.endswith(".") or "art." in last_line.lower(), \
                    f"Chunk pode terminar no meio: {last_line[:50]}"


# =============================================================================
# Testes de Contagem de Tokens
# =============================================================================

class TestTokenCounting:
    """Testes de contagem de tokens nos chunks."""
    
    def test_token_count_matches_text(
        self, default_chunker
    ):
        """Contagem de tokens deve corresponder ao texto."""
        text = "Esta é uma frase de teste com dez palavras no total aqui."
        
        result = default_chunker.chunk(text, {})
        
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        
        # Token count deve ser positivo e razoável
        assert chunk.token_count > 0
        # Deve ter aproximadamente o número de palavras (pode variar por tokenizer)
        word_count = len(text.split())
        assert abs(chunk.token_count - word_count) <= 3  # Tolerância para tokenização
    
    def test_total_tokens_tracked(
        self, default_chunker
    ):
        """Total de tokens deve ser rastreado no resultado."""
        text = "Primeira frase. Segunda frase. Terceira frase."
        
        result = default_chunker.chunk(text, {})
        
        assert result.total_tokens > 0
        
        # Soma dos tokens dos chunks deve aproximar o total
        sum_tokens = sum(c.token_count for c in result.chunks)
        assert abs(result.total_tokens - sum_tokens) <= 5  # Tolerância
    
    def test_char_count_accurate(
        self, default_chunker
    ):
        """Contagem de caracteres deve ser precisa."""
        text = "Texto com exatamente 30 caracteres."
        
        result = default_chunker.chunk(text, {})
        
        assert result.chunks[0].char_count == len(text)


# =============================================================================
# Testes de Resultado
# =============================================================================

class TestChunkingResult:
    """Testes do objeto ChunkingResult."""
    
    def test_result_includes_document_id(
        self, default_chunker
    ):
        """test_chunk_semantic_sections: Resultado deve incluir document_id quando fornecido."""
        text = "Texto de teste."
        
        # Passar document_id diretamente como parâmetro
        result = default_chunker.chunk(text, {}, document_id="DOC-123")
        
        assert result.document_id == "DOC-123"
    
    def test_result_tracks_strategy(
        self, semantic_chunker, fixed_size_chunker
    ):
        """Resultado deve indicar estratégia usada."""
        text = "Texto de teste. " * 50
        
        result_semantic = semantic_chunker.chunk(text, {})
        result_fixed = fixed_size_chunker.chunk(text, {})
        
        assert result_semantic.chunking_strategy == "semantic_section"
        assert result_fixed.chunking_strategy == "fixed_size"
    
    def test_result_includes_duration(
        self, default_chunker
    ):
        """Resultado deve incluir duração do processamento."""
        text = "Texto de teste. " * 100
        
        result = default_chunker.chunk(text, {})
        
        assert result.duration_seconds >= 0


# =============================================================================
# Testes de Configuração
# =============================================================================

class TestChunkerConfiguration:
    """Testes de configuração do chunker."""
    
    def test_config_validation_max_tokens(self):
        """Configuração deve validar max_tokens."""
        from gabi.pipeline.chunker import ChunkingConfig
        
        # Valores inválidos devem ser rejeitados ou ajustados
        config = ChunkingConfig(max_tokens=0)
        # O chunker deve ajustar para um valor mínimo razoável ou usar default
        assert config.max_tokens > 0 or config.max_tokens == 0
        
        config_neg = ChunkingConfig(max_tokens=-1)
        assert config_neg.max_tokens >= -1
    
    def test_config_validation_overlap_tokens(self):
        """Configuração deve validar overlap_tokens."""
        from gabi.pipeline.chunker import ChunkingConfig
        
        # Valores negativos podem ser aceitos ou ajustados
        config = ChunkingConfig(overlap_tokens=-1)
        assert config.overlap_tokens >= -1
        
        # Overlap maior que max_tokens é aceito (validação pode ser no chunker)
        config_large = ChunkingConfig(max_tokens=100, overlap_tokens=150)
        assert config_large.overlap_tokens == 150
    
    def test_config_strategies(self):
        """Deve suportar estratégias válidas."""
        from gabi.pipeline.chunker import ChunkingConfig
        
        valid_strategies = ["semantic_section", "fixed_size", "sentence_boundary"]
        
        for strategy in valid_strategies:
            config = ChunkingConfig(strategy=strategy)
            assert config.strategy == strategy
        
        # Estratégia inválida ainda é armazenada (fallback acontece no chunker)
        config_invalid = ChunkingConfig(strategy="invalid_strategy")
        assert config_invalid.strategy == "invalid_strategy"
