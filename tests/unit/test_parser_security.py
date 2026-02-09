"""Testes de segurança para o módulo parser.

Testa as funcionalidades de segurança incluindo:
- Size limits
- Page limits for PDFs
- Password-protected PDF handling
- HTML entity expansion protection (XSS, billion laughs)
- CSV row limits and smart delimiter detection
- Quarantine for suspicious files
"""

import io
import os
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Skip PDF tests if pdfplumber is not installed
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

from gabi.pipeline.parser import (
    CSVParser,
    HTMLParser,
    PDFParser,
    ParseErrorMetrics,
    get_parse_error_metrics,
    _quarantine_file,
    _check_html_entity_expansion,
    _sanitize_html_content,
    _detect_csv_dialect,
    MAX_PARSE_SIZE,
    MAX_CSV_ROWS,
    MAX_HTML_ENTITY_EXPANSION,
    MAX_HTML_SIZE,
    DEFAULT_PDF_MAX_PAGES,
    PDF_MAX_PAGES_HARD,
)
from gabi.pipeline.contracts import FetchedContent, FetchMetadata


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Mock de settings com valores inteiros para parser.
    
    Returns:
        MagicMock: Settings mockado com valores inteiros explícitos
    """
    from gabi.config import Settings, Environment
    
    # Create a real Settings instance to ensure all attributes return proper types
    settings = MagicMock(spec=Settings)
    
    # Parser settings - ensure these return actual integers, not Mock objects
    settings.parser_max_file_size = MAX_PARSE_SIZE
    settings.parser_max_total_size = MAX_PARSE_SIZE * 5
    settings.parser_max_workers = 4
    settings.parser_max_memory_mb = 512
    settings.parser_timeout_seconds = 300
    
    # General pipeline settings
    settings.pipeline_fetch_max_size_mb = 100
    settings.pipeline_fetch_timeout = 60
    settings.pipeline_max_memory_mb = 3584
    
    # Other commonly used settings that might be compared to integers
    settings.max_file_size = MAX_PARSE_SIZE
    settings.max_total_size = MAX_PARSE_SIZE * 5
    settings.max_memory_mb = 512
    settings.chunk_size = 8192
    settings.max_rows = MAX_CSV_ROWS
    
    return settings

@pytest.fixture
def oversized_content():
    """Conteúdo maior que o limite permitido."""
    return FetchedContent(
        url="https://example.com/large.csv",
        content=b"x" * (MAX_PARSE_SIZE + 1),
        size_bytes=MAX_PARSE_SIZE + 1,
        metadata=FetchMetadata(
            url="https://example.com/large.csv",
            status_code=200,
        ),
    )


@pytest.fixture
def csv_with_bom():
    """CSV com UTF-8 BOM."""
    # UTF-8 BOM followed by CSV content
    bom = b'\xef\xbb\xbf'
    csv_data = b'id,titulo\n1,Teste\n'
    content_bytes = bom + csv_data
    return FetchedContent(
        url="https://example.com/data.csv",
        content=content_bytes,
        size_bytes=len(content_bytes),
        metadata=FetchMetadata(
            url="https://example.com/data.csv",
            status_code=200,
        ),
    )


@pytest.fixture
def billion_laughs_html(monkeypatch):
    """HTML com ataque de expansão de entidades."""
    # Temporarily lower the threshold for testing
    import gabi.pipeline.parser as parser_module
    monkeypatch.setattr(parser_module, "MAX_HTML_ENTITY_EXPANSION", 5)
    
    content = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
        <!ENTITY lol "lol">
        <!ENTITY lol2 "&lol;&lol;&lol;&lol;">
    ]>
    <html><body>&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;</body></html>"""
    return FetchedContent(
        url="https://example.com/attack.html",
        content=content.encode('utf-8'),
        size_bytes=len(content),
        metadata=FetchMetadata(
            url="https://example.com/attack.html",
            status_code=200,
        ),
    )


@pytest.fixture
def xss_html():
    """HTML com tentativa de XSS."""
    content = """<html>
    <head><title>Test</title></head>
    <body>
        <script>alert('xss')</script>
        <img src="x" onerror="alert('xss')">
        <a href="javascript:void(0)">click</a>
        <p onclick="evil()">text</p>
        <div>safe content</div>
    </body>
    </html>"""
    return FetchedContent(
        url="https://example.com/xss.html",
        content=content.encode('utf-8'),
        size_bytes=len(content),
        metadata=FetchMetadata(
            url="https://example.com/xss.html",
            status_code=200,
        ),
    )


@pytest.fixture
def encrypted_pdf():
    """PDF simulado como criptografado (bytes falsos)."""
    # PDF header with /Encrypt marker
    content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Encrypt 2 0 R\n>>\nendobj"
    return FetchedContent(
        url="https://example.com/encrypted.pdf",
        content=content,
        size_bytes=len(content),
        metadata=FetchMetadata(
            url="https://example.com/encrypted.pdf",
            status_code=200,
        ),
    )


# =============================================================================
# Tests - Size Limits
# =============================================================================

class TestSizeLimits:
    """Testes de limites de tamanho."""
    
    @pytest.mark.asyncio
    async def test_csv_size_limit(self, oversized_content):
        """Deve rejeitar CSV maior que o limite."""
        parser = CSVParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(oversized_content, config)
        
        assert len(result.documents) == 0
        assert len(result.errors) == 1
        assert "SizeLimitExceeded" in result.errors[0]["error_type"]
        assert result.errors[0]["size_bytes"] > MAX_PARSE_SIZE
    
    @pytest.mark.asyncio
    async def test_html_size_limit(self):
        """Deve rejeitar HTML maior que o limite."""
        content = FetchedContent(
            url="https://example.com/large.html",
            content=b"x" * (MAX_HTML_SIZE + 1),
            size_bytes=MAX_HTML_SIZE + 1,
            metadata=FetchMetadata(
                url="https://example.com/large.html",
                status_code=200,
            ),
        )
        parser = HTMLParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(content, config)
        
        assert len(result.documents) == 0
        assert len(result.errors) == 1
        assert "SizeLimitExceeded" in result.errors[0]["error_type"]
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_PDFPLUMBER, reason="pdfplumber not installed")
    async def test_pdf_size_limit(self):
        """Deve rejeitar PDF maior que o limite."""
        content = FetchedContent(
            url="https://example.com/large.pdf",
            content=b"%PDF-1.4" + b"x" * MAX_PARSE_SIZE,
            size_bytes=MAX_PARSE_SIZE + 100,
            metadata=FetchMetadata(
                url="https://example.com/large.pdf",
                status_code=200,
            ),
        )
        parser = PDFParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(content, config)
        
        assert len(result.documents) == 0
        assert len(result.errors) == 1
        assert "SizeLimitExceeded" in result.errors[0]["error_type"]


# =============================================================================
# Tests - CSV Security
# =============================================================================

class TestCSVSecurity:
    """Testes de segurança do CSV Parser."""
    
    @pytest.mark.asyncio
    async def test_csv_row_limit(self):
        """Deve respeitar limite de linhas."""
        # Create CSV with many rows
        rows = ["id,name"] + [f"{i},Name{i}" for i in range(MAX_CSV_ROWS + 10)]
        content = "\n".join(rows).encode('utf-8')
        
        fetched = FetchedContent(
            url="https://example.com/large.csv",
            content=content,
            size_bytes=len(content),
            metadata=FetchMetadata(
                url="https://example.com/large.csv",
                status_code=200,
            ),
        )
        
        parser = CSVParser()
        config = {"source_id": "test", "max_rows": MAX_CSV_ROWS}
        
        result = await parser.parse(fetched, config)
        
        # Should have max_rows documents (minus header)
        assert len(result.documents) <= MAX_CSV_ROWS
        # Should have error about truncation
        assert any("RowLimitExceeded" in str(e.get("error_type", "")) for e in result.errors)
    
    @pytest.mark.asyncio
    async def test_csv_utf8_bom_handling(self, csv_with_bom):
        """Deve lidar corretamente com UTF-8 BOM."""
        parser = CSVParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(csv_with_bom, config)
        
        assert len(result.documents) == 1
        # Verify the BOM was stripped
        assert result.documents[0].metadata.get("detected_encoding") == "utf-8-sig"
    
    def test_detect_csv_dialect_comma(self):
        """Deve detectar delimitador vírgula."""
        sample = "id,name,value\n1,John,100\n2,Jane,200"
        delimiter, quotechar = _detect_csv_dialect(sample)
        assert delimiter == ","
        assert quotechar == '"'
    
    def test_detect_csv_dialect_semicolon(self):
        """Deve detectar delimitador ponto-e-vírgula."""
        sample = "id;name;value\n1;John;100\n2;Jane;200"
        delimiter, quotechar = _detect_csv_dialect(sample)
        assert delimiter == ";"
    
    def test_detect_csv_dialect_tab(self):
        """Deve detectar delimitador tab."""
        sample = "id\tname\tvalue\n1\tJohn\t100"
        delimiter, quotechar = _detect_csv_dialect(sample)
        assert delimiter == "\t"


# =============================================================================
# Tests - HTML Security
# =============================================================================

class TestHTMLSecurity:
    """Testes de segurança do HTML Parser."""
    
    @pytest.mark.asyncio
    async def test_html_xss_sanitization(self, xss_html):
        """Deve sanitizar tentativas de XSS."""
        parser = HTMLParser()
        config = {"source_id": "test", "sanitize": True}
        
        result = await parser.parse(xss_html, config)
        
        assert len(result.documents) == 1
        content = result.documents[0].content
        
        # Script tags should be removed
        assert "<script>" not in content
        assert "alert" not in content
        
        # Event handlers should be removed
        assert "onerror" not in content
        assert "onclick" not in content
        
        # But safe content should remain
        assert "safe content" in content
    
    @pytest.mark.asyncio
    async def test_html_entity_expansion_protection(self, billion_laughs_html):
        """Deve detectar e bloquear ataques de expansão de entidades."""
        parser = HTMLParser()
        config = {"source_id": "test"}
        
        result = await parser.parse(billion_laughs_html, config)
        
        assert len(result.documents) == 0
        assert len(result.errors) == 1
        assert "EntityExpansionAttack" in result.errors[0]["error_type"]
    
    def test_check_html_entity_expansion_safe(self):
        """Deve permitir HTML seguro."""
        content = "<html><body>Hello &amp; World</body></html>"
        is_safe, count = _check_html_entity_expansion(content, MAX_HTML_ENTITY_EXPANSION)
        assert is_safe is True
        assert count > 0  # Has one entity
    
    def test_sanitize_html_content(self):
        """Deve sanitizar conteúdo HTML perigoso."""
        content = """<script>alert('xss')</script>
        <p onclick="evil()" onload="bad()">text</p>
        <a href="javascript:alert(1)">link</a>"""
        
        sanitized = _sanitize_html_content(content)
        
        assert "<script>" not in sanitized
        assert "onclick" not in sanitized
        assert "onload" not in sanitized
        assert "javascript:" not in sanitized
        assert "<p>" in sanitized or "text" in sanitized


# =============================================================================
# Tests - PDF Security
# =============================================================================

@pytest.mark.skipif(not HAS_PDFPLUMBER, reason="pdfplumber not installed")
class TestPDFSecurity:
    """Testes de segurança do PDF Parser."""
    
    def test_is_password_protected_with_encrypt_marker(self, encrypted_pdf):
        """Deve detectar PDF criptografado pelo marcador /Encrypt."""
        parser = PDFParser()
        
        is_protected = parser._is_password_protected(encrypted_pdf.content)
        
        assert is_protected is True
    
    @pytest.mark.asyncio
    async def test_password_protected_pdf_rejected(self, encrypted_pdf):
        """Deve rejeitar PDF protegido por senha."""
        parser = PDFParser()
        config = {"source_id": "test"}
        
        # Mock the _is_password_protected to return True
        with patch.object(parser, '_is_password_protected', return_value=True):
            result = await parser.parse(encrypted_pdf, config)
        
        assert len(result.documents) == 0
        assert len(result.errors) == 1
        assert "PDFPasswordProtected" in result.errors[0]["error_type"]
        assert "password" in result.errors[0]["error"].lower()
    
    @pytest.mark.asyncio
    async def test_pdf_page_limit(self):
        """Deve respeitar limite de páginas."""
        # Create mock PDF with many pages
        mock_pages = [Mock(extract_text=Mock(return_value=f"Page {i}")) for i in range(DEFAULT_PDF_MAX_PAGES + 50)]
        
        mock_pdf = MagicMock()
        mock_pdf.pages = mock_pages
        mock_pdf.metadata = {"Title": "Test"}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        fetched = FetchedContent(
            url="https://example.com/large.pdf",
            content=b"%PDF-1.4 fake",
            size_bytes=100,
            metadata=FetchMetadata(
                url="https://example.com/large.pdf",
                status_code=200,
            ),
        )
        
        parser = PDFParser()
        config = {"source_id": "test", "extract_pages": True}
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, config)
        
        # Should have DEFAULT_PDF_MAX_PAGES documents
        assert len(result.documents) == DEFAULT_PDF_MAX_PAGES
        # Should have warning about page limit
        assert any("PageLimitExceeded" in str(e.get("error_type", "")) for e in result.errors)
    
    @pytest.mark.asyncio
    async def test_pdf_hard_page_limit(self):
        """Deve respeitar limite absoluto de páginas."""
        fetched = FetchedContent(
            url="https://example.com/large.pdf",
            content=b"%PDF-1.4 fake",
            size_bytes=100,
            metadata=FetchMetadata(
                url="https://example.com/large.pdf",
                status_code=200,
            ),
        )
        
        parser = PDFParser()
        # Request more pages than hard limit
        config = {"source_id": "test", "max_pages": PDF_MAX_PAGES_HARD + 1000}
        
        # Create mock PDF
        mock_pdf = MagicMock()
        mock_pdf.pages = [Mock(extract_text=Mock(return_value="text")) for _ in range(100)]
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)
        
        with patch('pdfplumber.open', return_value=mock_pdf):
            result = await parser.parse(fetched, config)
        
        # max_pages should be capped at PDF_MAX_PAGES_HARD
        assert len(result.documents) <= PDF_MAX_PAGES_HARD


# =============================================================================
# Tests - Error Metrics
# =============================================================================

class TestParseErrorMetrics:
    """Testes de métricas de erro."""
    
    def test_metrics_initialization(self):
        """Deve inicializar métricas vazias."""
        metrics = ParseErrorMetrics()
        
        assert metrics.total_parsed == 0
        assert metrics.total_failed == 0
        assert metrics.quarantine_count == 0
    
    def test_record_error(self):
        """Deve registrar erros corretamente."""
        metrics = ParseErrorMetrics()
        
        metrics.record_error("SizeLimitExceeded", "csv", quarantined=True)
        metrics.record_error("PDFPasswordProtected", "pdf", quarantined=False)
        
        assert metrics.total_failed == 2
        assert metrics.quarantine_count == 1
        assert metrics.errors_by_type["SizeLimitExceeded"] == 1
        assert metrics.errors_by_format["csv"] == 1
        assert metrics.errors_by_format["pdf"] == 1
    
    def test_record_success(self):
        """Deve registrar sucessos corretamente."""
        metrics = ParseErrorMetrics()
        
        metrics.record_success("csv")
        metrics.record_success("html")
        
        assert metrics.total_parsed == 2
    
    def test_get_stats(self):
        """Deve retornar estatísticas corretas."""
        metrics = ParseErrorMetrics()
        
        metrics.record_success("csv")
        metrics.record_success("html")
        metrics.record_error("PDFPasswordProtected", "pdf")
        
        stats = metrics.get_stats()
        
        assert stats["total_parsed"] == 2
        assert stats["total_failed"] == 1
        assert stats["failure_rate"] == 1/3
        assert "errors_by_type" in stats
        assert "errors_by_format" in stats
    
    def test_global_metrics_instance(self):
        """Deve retornar instância global de métricas."""
        metrics1 = get_parse_error_metrics()
        metrics2 = get_parse_error_metrics()
        
        assert metrics1 is metrics2


# =============================================================================
# Tests - Quarantine
# =============================================================================

class TestQuarantine:
    """Testes de quarentena de arquivos."""
    
    def test_quarantine_disabled(self, monkeypatch):
        """Deve respeitar configuração de desativação de quarentena."""
        monkeypatch.setenv("GABI_QUARANTINE_ENABLED", "false")
        
        # No need to reload module - _get_quarantine_config() reads env vars fresh
        from gabi.pipeline import parser
        
        fetched = FetchedContent(
            url="https://example.com/suspicious.csv",
            content=b"suspicious",
            size_bytes=10,
            metadata=FetchMetadata(
                url="https://example.com/suspicious.csv",
                status_code=200,
            ),
        )
        
        result = parser._quarantine_file(fetched, "TestReason", {})
        
        # Should return empty string when disabled
        assert result == ""
    
    def test_quarantine_file_creation(self, tmp_path, monkeypatch):
        """Deve criar arquivo em quarentena."""
        monkeypatch.setenv("GABI_QUARANTINE_ENABLED", "true")
        monkeypatch.setenv("GABI_QUARANTINE_DIR", str(tmp_path))
        
        # No need to reload module - _get_quarantine_config() reads env vars fresh
        from gabi.pipeline import parser
        
        fetched = FetchedContent(
            url="https://example.com/suspicious.csv",
            content=b"suspicious content",
            size_bytes=16,
            metadata=FetchMetadata(
                url="https://example.com/suspicious.csv",
                status_code=200,
            ),
        )
        
        result = parser._quarantine_file(fetched, "SuspiciousContent", {"reason": "test"})
        
        assert result != ""
        assert os.path.exists(result)
        
        # Check metadata file was created
        meta_path = result + ".meta"
        assert os.path.exists(meta_path)


# =============================================================================
# Tests - Constants
# =============================================================================

class TestSecurityConstants:
    """Testes de constantes de segurança."""
    
    def test_max_parse_size(self):
        """MAX_PARSE_SIZE deve ser 100MB."""
        assert MAX_PARSE_SIZE == 100 * 1024 * 1024
    
    def test_max_csv_rows(self):
        """MAX_CSV_ROWS deve ser 1 milhão."""
        assert MAX_CSV_ROWS == 1_000_000
    
    def test_max_html_entity_expansion(self):
        """MAX_HTML_ENTITY_EXPANSION deve ser 10000."""
        assert MAX_HTML_ENTITY_EXPANSION == 10_000
    
    def test_default_pdf_max_pages(self):
        """DEFAULT_PDF_MAX_PAGES deve ser 1000."""
        assert DEFAULT_PDF_MAX_PAGES == 1000
    
    def test_pdf_max_pages_hard(self):
        """PDF_MAX_PAGES_HARD deve ser 10000."""
        assert PDF_MAX_PAGES_HARD == 10_000
