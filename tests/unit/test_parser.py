"""Testes unitários para o módulo parser.

Testa as funcionalidades dos parsers incluindo:
- CSV Parser
- HTML Parser
- PDF Parser
- Parser Registry
"""

import io
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from gabi.pipeline.parser import (
    BaseParser,
    ParserRegistry,
    CSVParser,
    HTMLParser,
    PDFParser,
    get_registry,
    register_parser,
    get_parser,
)
from gabi.pipeline.contracts import FetchedContent, FetchMetadata, ParseResult, ParsedDocument


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_csv_content():
    """Conteúdo CSV de exemplo."""
    return (
        "id,titulo,relator,ementa\n"
        "1,Acórdão 1234/2024,Ministro Teste,Ementa do acórdão\n"
        "2,Acórdão 5678/2024,Ministro Outro,Outra ementa\n"
    )


@pytest.fixture
def sample_csv_bytes(sample_csv_content):
    """Bytes do CSV de exemplo."""
    return sample_csv_content.encode('utf-8')


@pytest.fixture
def sample_html_content():
    """Conteúdo HTML de exemplo."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Acórdão 1234/2024</title>
        <script>alert('test');</script>
        <style>body { font-family: Arial; }</style>
    </head>
    <body>
        <nav>Menu de navegação</nav>
        <main>
            <h1>EMENTA</h1>
            <p>Licitação. Pregão Eletrônico. Impugnação ao edital.</p>
            <h2>RELATÓRIO</h2>
            <p>O Ministro relator apresentou os fatos pertinentes.</p>
        </main>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_bytes(sample_html_content):
    """Bytes do HTML de exemplo."""
    return sample_html_content.encode('utf-8')


@pytest.fixture
def sample_csv_config():
    """Configuração para parser CSV."""
    return {
        "source_id": "tcu_acordaos",
        "title_column": "titulo",
        "content_columns": ["relator", "ementa"],
        "delimiter": ",",
    }


@pytest.fixture
def sample_html_config():
    """Configuração para parser HTML."""
    return {
        "source_id": "tcu_portal",
        "title_selector": "title",
        "remove_tags": ["script", "style", "nav"],
    }


@pytest.fixture
def sample_pdf_config():
    """Configuração para parser PDF."""
    return {
        "source_id": "tcu_pdfs",
        "extract_pages": False,
    }


@pytest.fixture
def fetched_csv(sample_csv_bytes):
    """FetchedContent para CSV."""
    return FetchedContent(
        url="https://example.com/data.csv",
        content=sample_csv_bytes,
        metadata=FetchMetadata(
            url="https://example.com/data.csv",
            status_code=200,
            content_type="text/csv",
        ),
    )


@pytest.fixture
def fetched_html(sample_html_bytes):
    """FetchedContent para HTML."""
    return FetchedContent(
        url="https://example.com/page.html",
        content=sample_html_bytes,
        metadata=FetchMetadata(
            url="https://example.com/page.html",
            status_code=200,
            content_type="text/html",
        ),
    )


# =============================================================================
# Testes do ParserRegistry
# =============================================================================

class TestParserRegistry:
    """Testes do registro de parsers."""
    
    def test_registry_initialization(self):
        """Deve inicializar com registro vazio."""
        registry = ParserRegistry()
        assert registry.list_formats() == []
    
    def test_register_parser(self):
        """Deve registrar um parser."""
        registry = ParserRegistry()
        parser = Mock(spec=BaseParser)
        
        registry.register("csv", parser)
        
        assert "csv" in registry.list_formats()
        assert registry.get_parser("csv") is parser
    
    def test_register_case_insensitive(self):
        """Deve registrar com nome case-insensitive."""
        registry = ParserRegistry()
        parser = Mock(spec=BaseParser)
        
        registry.register("CSV", parser)
        
        assert registry.get_parser("csv") is parser
        assert registry.get_parser("CSV") is parser
    
    def test_unregister_parser(self):
        """Deve remover um parser."""
        registry = ParserRegistry()
        parser = Mock(spec=BaseParser)
        
        registry.register("csv", parser)
        assert registry.unregister("csv") is True
        assert registry.get_parser("csv") is None
    
    def test_unregister_nonexistent(self):
        """Deve retornar False ao remover parser inexistente."""
        registry = ParserRegistry()
        assert registry.unregister("nonexistent") is False
    
    def test_has_parser(self):
        """Deve verificar se parser existe."""
        registry = ParserRegistry()
        parser = Mock(spec=BaseParser)
        
        registry.register("csv", parser)
        
        assert registry.has_parser("csv") is True
        assert registry.has_parser("nonexistent") is False


# =============================================================================
# Testes do CSVParser
# =============================================================================

class TestCSVParser:
    """Testes do parser CSV."""
    
    @pytest.mark.asyncio
    async def test_parse_csv_basic(self, fetched_csv, sample_csv_config):
        """Deve parsear CSV básico."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        assert isinstance(result, ParseResult)
        assert len(result.documents) == 2
        assert len(result.errors) == 0
        assert result.raw_content_size == len(fetched_csv.content)
    
    @pytest.mark.asyncio
    async def test_parse_csv_with_title_column(self, fetched_csv, sample_csv_config):
        """Deve extrair título da coluna especificada."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        assert result.documents[0].title == "Acórdão 1234/2024"
        assert result.documents[1].title == "Acórdão 5678/2024"
    
    @pytest.mark.asyncio
    async def test_parse_csv_with_content_columns(self, fetched_csv, sample_csv_config):
        """Deve extrair conteúdo das colunas especificadas."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        doc = result.documents[0]
        assert "Ministro Teste" in doc.content
        assert "Ementa do acórdão" in doc.content
    
    @pytest.mark.asyncio
    async def test_parse_csv_without_content_columns(self, fetched_csv, sample_csv_config):
        """Deve usar todas as colunas se nenhuma especificada."""
        parser = CSVParser()
        config = {**sample_csv_config}
        del config["content_columns"]
        
        result = await parser.parse(fetched_csv, config)
        
        doc = result.documents[0]
        assert "id: 1" in doc.content
        assert "titulo: Acórdão 1234/2024" in doc.content
    
    @pytest.mark.asyncio
    async def test_parse_csv_with_custom_delimiter(self):
        """Deve usar delimitador customizado."""
        content = "id;titulo;relator\n1;Acórdão;Ministro\n"
        fetched = FetchedContent(
            url="https://example.com/data.csv",
            content=content.encode('utf-8'),
            metadata=FetchMetadata(
                url="https://example.com/data.csv",
                status_code=200,
                content_type="text/csv",
            ),
        )
        parser = CSVParser()
        config = {
            "source_id": "test",
            "delimiter": ";",
        }
        
        result = await parser.parse(fetched, config)
        
        assert len(result.documents) == 1
        assert "Acórdão" in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_csv_empty_file(self):
        """Deve lidar com arquivo CSV vazio."""
        fetched = FetchedContent(
            url="https://example.com/empty.csv",
            content=b"",
            metadata=FetchMetadata(
                url="https://example.com/empty.csv",
                status_code=200,
            ),
        )
        parser = CSVParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(fetched, config)
        
        # Deve retornar vazio ou erro controlado
        assert isinstance(result, ParseResult)
    
    @pytest.mark.asyncio
    async def test_parse_csv_encoding_error(self):
        """Deve tratar erro de encoding."""
        fetched = FetchedContent(
            url="https://example.com/data.csv",
            content=b"\xff\xfeinvalid utf-8",
            metadata=FetchMetadata(
                url="https://example.com/data.csv",
                status_code=200,
            ),
        )
        parser = CSVParser()
        config = {"source_id": "test", "encoding": "utf-8"}
        
        result = await parser.parse(fetched, config)
        
        assert len(result.errors) > 0
        assert any("encoding" in str(e.get("error", "")).lower() for e in result.errors)
    
    @pytest.mark.asyncio
    async def test_parse_csv_generate_document_id(self, fetched_csv, sample_csv_config):
        """Deve gerar ID único para documento."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        doc = result.documents[0]
        assert doc.document_id.startswith("doc_")
        assert "tcu_acordaos" in doc.document_id
    
    @pytest.mark.asyncio
    async def test_parse_csv_content_hash(self, fetched_csv, sample_csv_config):
        """Deve gerar hash do conteúdo."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        doc = result.documents[0]
        assert doc.content_hash is not None
        assert len(doc.content_hash) == 64  # SHA-256 hex
    
    @pytest.mark.asyncio
    async def test_parse_csv_preview(self, fetched_csv, sample_csv_config):
        """Deve gerar preview do conteúdo."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        doc = result.documents[0]
        assert doc.content_preview is not None
        assert len(doc.content_preview) <= 503  # 500 + "..."
    
    @pytest.mark.asyncio
    async def test_parse_csv_with_mapping_transforms(self):
        """Deve aplicar transforms do mapping aos valores."""
        content = 'KEY,TITULO,EMENTA\n"123","\"Acordao 123\"","<p>Texto</p>"\n'
        fetched = FetchedContent(
            url="https://example.com/data.csv",
            content=content.encode('utf-8'),
            metadata=FetchMetadata(
                url="https://example.com/data.csv",
                status_code=200,
                content_type="text/csv",
            ),
        )
        parser = CSVParser()
        config = {
            "source_id": "test",
            "mapping": {
                "document_id": {"from": "KEY", "transform": "strip_quotes"},
                "title": {"from": "TITULO", "transform": "strip_quotes"},
                "text": {"from": "EMENTA", "transform": "strip_html"},
            },
        }
        
        result = await parser.parse(fetched, config)
        
        assert len(result.documents) == 1
        raw_data = result.documents[0].metadata["raw_data"]
        # Verify strip_quotes was applied
        assert raw_data["document_id"] == "123"  # Quotes removed
        assert raw_data["title"] == "Acordao 123"  # Quotes removed
        # Verify strip_html was applied
        assert raw_data["text"] == "Texto"  # HTML tags removed
    
    @pytest.mark.asyncio
    async def test_parse_csv_mapping_without_transform(self):
        """Deve funcionar com mapping sem transform especificado."""
        content = 'ID,NOME\n1,Joao\n'
        fetched = FetchedContent(
            url="https://example.com/data.csv",
            content=content.encode('utf-8'),
            metadata=FetchMetadata(
                url="https://example.com/data.csv",
                status_code=200,
                content_type="text/csv",
            ),
        )
        parser = CSVParser()
        config = {
            "source_id": "test",
            "mapping": {
                "document_id": {"from": "ID"},
                "name": {"from": "NOME"},
            },
        }
        
        result = await parser.parse(fetched, config)
        
        assert len(result.documents) == 1
        raw_data = result.documents[0].metadata["raw_data"]
        assert raw_data["document_id"] == "1"
        assert raw_data["name"] == "Joao"


# =============================================================================
# Testes do HTMLParser
# =============================================================================

class TestHTMLParser:
    """Testes do parser HTML."""
    
    @pytest.mark.asyncio
    async def test_parse_html_basic(self, fetched_html, sample_html_config):
        """Deve parsear HTML básico."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        assert isinstance(result, ParseResult)
        assert len(result.documents) == 1
        assert len(result.errors) == 0
    
    @pytest.mark.asyncio
    async def test_parse_html_extract_title(self, fetched_html, sample_html_config):
        """Deve extrair título do HTML."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        assert result.documents[0].title == "Acórdão 1234/2024"
    
    @pytest.mark.asyncio
    async def test_parse_html_remove_scripts(self, fetched_html, sample_html_config):
        """Deve remover scripts do conteúdo."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        assert "alert" not in result.documents[0].content
        assert "<script>" not in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_html_remove_styles(self, fetched_html, sample_html_config):
        """Deve remover styles do conteúdo."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        assert "font-family" not in result.documents[0].content
        assert "<style>" not in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_html_remove_nav(self, fetched_html, sample_html_config):
        """Deve remover elementos de navegação."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        assert "Menu de navegação" not in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_html_extract_main_content(self, fetched_html, sample_html_config):
        """Deve extrair conteúdo principal."""
        parser = HTMLParser()
        
        result = await parser.parse(fetched_html, sample_html_config)
        
        content = result.documents[0].content
        assert "EMENTA" in content
        assert "RELATÓRIO" in content
        assert "Licitação" in content
    
    @pytest.mark.asyncio
    async def test_parse_html_with_css_selector(self, sample_html_bytes):
        """Deve usar seletor CSS para extrair seção."""
        fetched = FetchedContent(
            url="https://example.com/page.html",
            content=sample_html_bytes,
            metadata=FetchMetadata(
                url="https://example.com/page.html",
                status_code=200,
                content_type="text/html",
            ),
        )
        parser = HTMLParser()
        config = {
            "source_id": "test",
            "css_selector": "main",
            "title_selector": "h1",
        }
        
        result = await parser.parse(fetched, config)
        
        assert "EMENTA" in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_html_body_fallback(self):
        """Deve usar body como fallback se não houver main/article."""
        html = "<html><body><p>Conteúdo do body</p></body></html>"
        fetched = FetchedContent(
            url="https://example.com/page.html",
            content=html.encode('utf-8'),
            metadata=FetchMetadata(
                url="https://example.com/page.html",
                status_code=200,
                content_type="text/html",
            ),
        )
        parser = HTMLParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(fetched, config)
        
        assert "Conteúdo do body" in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_html_encoding_error(self):
        """Deve tratar erro de encoding."""
        fetched = FetchedContent(
            url="https://example.com/page.html",
            content=b"\xff\xfeinvalid utf-8",
            metadata=FetchMetadata(
                url="https://example.com/page.html",
                status_code=200,
            ),
        )
        parser = HTMLParser()
        config = {"source_id": "test", "encoding": "utf-8"}
        
        result = await parser.parse(fetched, config)
        
        assert len(result.errors) > 0
        assert any("encoding" in str(e.get("error", "")).lower() for e in result.errors)
    
    @pytest.mark.asyncio
    async def test_parse_html_empty_content(self):
        """Deve lidar com HTML vazio."""
        fetched = FetchedContent(
            url="https://example.com/empty.html",
            content=b"",
            metadata=FetchMetadata(
                url="https://example.com/empty.html",
                status_code=200,
            ),
        )
        parser = HTMLParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(fetched, config)
        
        assert isinstance(result, ParseResult)


# =============================================================================
# Testes do PDFParser
# =============================================================================

class TestPDFParser:
    """Testes do parser PDF."""
    
    @pytest.mark.asyncio
    async def test_parse_pdf_basic(self, sample_pdf_config):
        """Deve parsear PDF básico."""
        # Mock do pdfplumber - precisa suportar context manager
        mock_page = Mock()
        mock_page.extract_text.return_value = "Conteúdo da página 1"
        
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {"Title": "Documento Teste"}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"%PDF-1.4 fake pdf content",
            metadata=FetchMetadata(
                url="https://example.com/doc.pdf",
                status_code=200,
                content_type="application/pdf",
            ),
        )
        
        parser = PDFParser()
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, sample_pdf_config)
        
        assert isinstance(result, ParseResult)
        assert len(result.documents) == 1
    
    @pytest.mark.asyncio
    async def test_parse_pdf_extract_title_from_metadata(self, sample_pdf_config):
        """Deve extrair título dos metadados do PDF."""
        mock_page = Mock()
        mock_page.extract_text.return_value = "Conteúdo"
        
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {"Title": "Meu Documento"}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"fake",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, sample_pdf_config)
        
        assert result.documents[0].title == "Meu Documento"
    
    @pytest.mark.asyncio
    async def test_parse_pdf_single_document_mode(self, sample_pdf_config):
        """Deve criar documento único quando extract_pages=False."""
        mock_pages = [
            Mock(extract_text=Mock(return_value="Página 1")),
            Mock(extract_text=Mock(return_value="Página 2")),
        ]
        
        mock_pdf = MagicMock()
        mock_pdf.pages = mock_pages
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"fake",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        config = {**sample_pdf_config, "extract_pages": False}
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, config)
        
        assert len(result.documents) == 1
        assert "Página 1" in result.documents[0].content
        assert "Página 2" in result.documents[0].content
    
    @pytest.mark.asyncio
    async def test_parse_pdf_extract_pages_mode(self, sample_pdf_config):
        """Deve criar documento por página quando extract_pages=True."""
        mock_pages = [
            Mock(extract_text=Mock(return_value="Conteúdo página 1")),
            Mock(extract_text=Mock(return_value="Conteúdo página 2")),
        ]
        
        mock_pdf = MagicMock()
        mock_pdf.pages = mock_pages
        mock_pdf.metadata = {"Title": "Doc Teste"}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"fake",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        config = {**sample_pdf_config, "extract_pages": True}
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, config)
        
        assert len(result.documents) == 2
        assert result.documents[0].metadata["page_number"] == 1
        assert result.documents[1].metadata["page_number"] == 2
    
    @pytest.mark.asyncio
    async def test_parse_pdf_skip_empty_pages(self, sample_pdf_config):
        """Deve ignorar páginas vazias."""
        mock_pages = [
            Mock(extract_text=Mock(return_value="Conteúdo")),
            Mock(extract_text=Mock(return_value="")),  # Página vazia
            Mock(extract_text=Mock(return_value="Mais conteúdo")),
        ]
        
        mock_pdf = MagicMock()
        mock_pdf.pages = mock_pages
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"fake",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        config = {**sample_pdf_config, "extract_pages": True}
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, config)
        
        # Deve ter apenas 2 documentos (páginas com conteúdo)
        assert len(result.documents) == 2
    
    @pytest.mark.asyncio
    async def test_parse_pdf_metadata(self, sample_pdf_config):
        """Deve incluir metadados do PDF."""
        mock_page = Mock()
        mock_page.extract_text.return_value = "Conteúdo"
        
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {
            "Title": "Título",
            "Author": "Autor",
            "CreationDate": "20240101",
        }
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"fake",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, sample_pdf_config)
        
        metadata = result.documents[0].metadata
        assert metadata["pdf_title"] == "Título"
        assert metadata["total_pages"] == 1
        assert "pdf_metadata" in metadata
    
    @pytest.mark.asyncio
    async def test_parse_pdf_error_handling(self, sample_pdf_config):
        """Deve tratar erros de parsing."""
        fetched = FetchedContent(
            url="https://example.com/doc.pdf",
            content=b"invalid pdf content",
            metadata=FetchMetadata(url="https://example.com/doc.pdf", status_code=200),
        )
        
        parser = PDFParser()
        
        with patch('pdfplumber.open', side_effect=Exception("PDF corrupt")):
            result = await parser.parse(fetched, sample_pdf_config)
        
        assert len(result.errors) > 0
        assert "pdf" in str(result.errors[0].get("error", "")).lower()


# =============================================================================
# Testes de Integração Simples
# =============================================================================

class TestParserIntegration:
    """Testes de integração entre componentes."""
    
    def test_global_registry_has_built_in_parsers(self):
        """O registro global deve ter parsers built-in registrados."""
        registry = get_registry()
        
        assert registry.has_parser("csv")
        assert registry.has_parser("html")
        assert registry.has_parser("pdf")
    
    def test_get_parser_returns_correct_instance(self):
        """Deve retornar instância correta do parser."""
        csv_parser = get_parser("csv")
        html_parser = get_parser("html")
        pdf_parser = get_parser("pdf")
        
        assert isinstance(csv_parser, CSVParser)
        assert isinstance(html_parser, HTMLParser)
        assert isinstance(pdf_parser, PDFParser)
    
    def test_register_parser_global(self):
        """Deve registrar parser no registro global."""
        custom_parser = Mock(spec=BaseParser)
        
        register_parser("custom", custom_parser)
        
        assert get_parser("custom") is custom_parser
    
    @pytest.mark.asyncio
    async def test_parse_result_timing(self, fetched_csv, sample_csv_config):
        """Deve incluir duração do parsing no resultado."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        assert result.duration_seconds >= 0
    
    @pytest.mark.asyncio
    async def test_parse_result_sizes(self, fetched_csv, sample_csv_config):
        """Deve reportar tamanhos corretos."""
        parser = CSVParser()
        
        result = await parser.parse(fetched_csv, sample_csv_config)
        
        assert result.raw_content_size == len(fetched_csv.content)
        assert result.parsed_content_size > 0
        assert result.parsed_content_size <= result.raw_content_size * 10  # Geralmente maior após parse
