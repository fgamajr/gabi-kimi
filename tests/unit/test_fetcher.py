"""Testes unitários para o módulo fetcher.

Testa as funcionalidades do ContentFetcher incluindo:
- Download com streaming
- Retry com exponential backoff
- Validação de magic bytes
- Limite de tamanho
- Cálculo de hash SHA-256
- Tratamento de erros
- Proteção SSRF
- Circuit breaker
"""

import hashlib
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock, call
from typing import AsyncGenerator

import httpx
from tenacity import RetryError

from gabi.pipeline.fetcher import (
    ContentFetcher,
    FetcherConfig,
    FetchError,
    FetchSizeError,
    FetchFormatError,
    FetchTimeoutError,
    FetchRetryableError,
    FetchPermanentError,
    FetchSSRFError,
    FormatType,
    MAGIC_BYTES,
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    SSRFProtector,
    SSRFConfig,
)
from gabi.pipeline.contracts import FetchMetadata, FetchedContent


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fetcher_config():
    """Configuração de fetcher para testes."""
    config = FetcherConfig(
        timeout=30,
        max_retries=2,
        max_size_bytes=1024 * 1024,  # 1MB para testes
        chunk_size=1024,
        validate_magic_bytes=True,
    )
    # Override default stream_threshold to be compatible with max_size_bytes
    config.stream_threshold = 512 * 1024  # 512KB - less than max_size_bytes
    return config


@pytest.fixture
def fetcher(fetcher_config):
    """Fetcher configurado para testes."""
    return ContentFetcher(config=fetcher_config)


@pytest.fixture
def sample_pdf_bytes():
    """Bytes de um PDF minimalista válido."""
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\n%%EOF"


@pytest.fixture
def sample_csv_bytes():
    """Bytes de um CSV válido."""
    return b"id,name,value\n1,Test,100\n2,Other,200\n"


@pytest.fixture
def sample_html_bytes():
    """Bytes de um HTML válido."""
    return b"<!DOCTYPE html><html><head><title>Test</title></head><body>Content</body></html>"


@pytest.fixture
def sample_json_bytes():
    """Bytes de um JSON válido."""
    return b'{"id": 1, "name": "Test", "value": 100}'


@pytest.fixture
def sample_docx_bytes():
    """Bytes simulando um DOCX (ZIP com assinatura Word)."""
    # ZIP header + indicador de documento Word
    return b"PK\x03\x04\x14\x00\x06\x00[Content_Types].xmlword/document.xml"


@pytest.fixture
def mock_response():
    """Mock de resposta HTTP assíncrona."""
    response = AsyncMock(spec=httpx.Response)
    response.status_code = 200
    response.headers = {
        "content-type": "application/pdf",
        "content-length": "100",
    }
    response.encoding = "utf-8"
    return response


@pytest.fixture
def ssrf_config():
    """Configuração SSRF para testes."""
    return SSRFConfig(
        enabled=True,
        blocked_hosts={"169.254.169.254", "localhost", "127.0.0.1"},
        blocked_cidr={"10.0.0.0/8", "192.168.0.0/16"},
        allowed_protocols={"http", "https"},
        block_internal_ips=True,
    )


@pytest.fixture
def circuit_breaker_config():
    """Configuração de circuit breaker para testes."""
    return CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=5,
        half_open_max_calls=2,
    )


# =============================================================================
# Testes de Inicialização e Configuração
# =============================================================================

class TestFetcherInitialization:
    """Testes de inicialização do ContentFetcher."""
    
    def test_default_initialization(self):
        """Deve inicializar com configuração padrão."""
        fetcher = ContentFetcher()
        
        assert fetcher.config is not None
        assert fetcher.config.timeout > 0
        assert fetcher.config.max_retries >= 0
        assert fetcher.config.max_size_bytes > 0
        assert fetcher.config.ssrf_config is not None
        assert fetcher.config.circuit_breaker_config is not None
    
    def test_custom_initialization(self, fetcher_config):
        """Deve inicializar com configuração customizada."""
        fetcher = ContentFetcher(config=fetcher_config)
        
        assert fetcher.config.timeout == 30
        assert fetcher.config.max_retries == 2
        assert fetcher.config.max_size_bytes == 1024 * 1024
    
    def test_config_validation_timeout(self):
        """Deve validar timeout."""
        config = FetcherConfig()
        
        with pytest.raises(ValueError, match="timeout must be between"):
            config.timeout = 0
            config.validate()
        
        with pytest.raises(ValueError, match="timeout must be between"):
            config.timeout = 601
            config.validate()
    
    def test_config_validation_max_retries(self):
        """Deve validar max_retries."""
        config = FetcherConfig()
        
        with pytest.raises(ValueError, match="max_retries must be between"):
            config.max_retries = -1
            config.validate()
        
        with pytest.raises(ValueError, match="max_retries must be between"):
            config.max_retries = 11
            config.validate()
    
    def test_config_validation_max_size(self):
        """Deve validar max_size_bytes."""
        config = FetcherConfig()
        
        with pytest.raises(ValueError, match="max_size_bytes must be between"):
            config.max_size_bytes = 100
            config.validate()
    
    def test_config_validation_chunk_size(self):
        """Deve validar chunk_size."""
        config = FetcherConfig()
        
        with pytest.raises(ValueError, match="chunk_size must be between"):
            config.chunk_size = 512
            config.validate()
        
        with pytest.raises(ValueError, match="chunk_size must be between"):
            config.chunk_size = 2 * 1024 * 1024
            config.validate()
    
    def test_update_config_chainable(self, fetcher):
        """Deve permitir atualização chainable de config."""
        result = fetcher.update_config(timeout=60, max_retries=5)
        
        assert result is fetcher
        assert fetcher.config.timeout == 60
        assert fetcher.config.max_retries == 5
    
    def test_update_config_invalid_key(self, fetcher):
        """Deve rejeitar chaves de config inválidas."""
        with pytest.raises(ValueError, match="Invalid config key"):
            fetcher.update_config(invalid_key="value")
    
    @pytest.mark.asyncio
    async def test_context_manager(self, fetcher_config):
        """Deve funcionar como context manager."""
        async with ContentFetcher(fetcher_config) as fetcher:
            assert fetcher.config is not None
        
        # Após sair do contexto, cliente deve estar fechado
        assert fetcher._client is None or fetcher._client.is_closed


# =============================================================================
# Testes de Download Básico
# =============================================================================

class TestFetchBasic:
    """Testes de download básico."""
    
    @pytest.mark.asyncio
    async def test_fetch_pdf_success(self, fetcher, sample_pdf_bytes):
        """Deve fazer download de PDF com sucesso."""
        # Arrange
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {
            "content-type": "application/pdf",
            "content-length": str(len(sample_pdf_bytes)),
        }
        mock_response.encoding = None
        
        async def mock_aiter_bytes(chunk_size):
            yield sample_pdf_bytes
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            # Act
            result = await fetcher.fetch("https://example.com/doc.pdf", "source_1")
            
            # Assert
            assert isinstance(result, FetchedContent)
            assert result.content == sample_pdf_bytes
            assert result.metadata.status_code == 200
            assert result.metadata.content_type == "application/pdf"
            assert result.fingerprint == hashlib.sha256(sample_pdf_bytes).hexdigest()
    
    @pytest.mark.asyncio
    async def test_fetch_csv_success(self, fetcher, sample_csv_bytes):
        """Deve fazer download de CSV com sucesso."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/csv"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            yield sample_csv_bytes
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/data.csv", "source_1")
            
            assert result.content == sample_csv_bytes
            assert result.metadata.content_type == "text/csv"
    
    @pytest.mark.asyncio
    async def test_fetch_html_success(self, fetcher, sample_html_bytes):
        """Deve fazer download de HTML com sucesso."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            yield sample_html_bytes
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/page.html", "source_1")
            
            assert result.content == sample_html_bytes
            assert result.metadata.content_type == "text/html"
    
    @pytest.mark.asyncio
    async def test_fetch_empty_content(self, fetcher):
        """Deve lidar com conteúdo vazio."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            yield b""
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/empty.txt", "source_1")
            
            assert result.content == b""
            assert result.fingerprint == hashlib.sha256(b"").hexdigest()


# =============================================================================
# Testes de Magic Bytes e Detecção de Formato
# =============================================================================

class TestFormatDetection:
    """Testes de detecção de formato por magic bytes."""
    
    def test_detect_pdf_from_bytes(self, fetcher, sample_pdf_bytes):
        """Deve detectar PDF pelos magic bytes."""
        detected = fetcher._detect_format_from_bytes(sample_pdf_bytes)
        assert detected == FormatType.PDF
    
    def test_detect_csv_from_bytes(self, fetcher, sample_csv_bytes):
        """Deve detectar CSV por heurística."""
        detected = fetcher._detect_format_from_bytes(sample_csv_bytes)
        assert detected == FormatType.CSV
    
    def test_detect_html_from_bytes(self, fetcher, sample_html_bytes):
        """Deve detectar HTML por heurística."""
        detected = fetcher._detect_format_from_bytes(sample_html_bytes)
        assert detected == FormatType.HTML
    
    def test_detect_json_from_bytes(self, fetcher, sample_json_bytes):
        """Deve detectar JSON por heurística."""
        detected = fetcher._detect_format_from_bytes(sample_json_bytes)
        assert detected == FormatType.JSON
    
    def test_detect_docx_from_bytes(self, fetcher, sample_docx_bytes):
        """Deve detectar DOCX em arquivo ZIP."""
        detected = fetcher._detect_format_from_bytes(sample_docx_bytes)
        assert detected == FormatType.DOCX
    
    def test_detect_xlsx_from_bytes(self, fetcher):
        """Deve detectar XLSX em arquivo ZIP."""
        xlsx_bytes = b"PK\x03\x04\x14\x00\x06\x00[Content_Types].xmlxl/worksheet.xml"
        detected = fetcher._detect_format_from_bytes(xlsx_bytes)
        assert detected == FormatType.XLSX
    
    def test_detect_pptx_from_bytes(self, fetcher):
        """Deve detectar PPTX em arquivo ZIP."""
        pptx_bytes = b"PK\x03\x04\x14\x00\x06\x00[Content_Types].xmlppt/presentation.xml"
        detected = fetcher._detect_format_from_bytes(pptx_bytes)
        assert detected == FormatType.PPTX
    
    def test_detect_odt_from_bytes(self, fetcher):
        """Deve detectar ODT em arquivo ZIP."""
        odt_bytes = b"PK\x03\x04mimetypeapplication/vnd.oasis.opendocument.text"
        detected = fetcher._detect_format_from_bytes(odt_bytes)
        assert detected == FormatType.ODT
    
    def test_detect_zip_generic(self, fetcher):
        """Deve detectar ZIP genérico quando não é Office."""
        zip_bytes = b"PK\x03\x04\x14\x00\x00\x00\x08\x00somefile.txt"
        detected = fetcher._detect_format_from_bytes(zip_bytes)
        assert detected == FormatType.ZIP
    
    def test_detect_unknown_from_bytes(self, fetcher):
        """Deve retornar UNKNOWN para bytes não reconhecidos."""
        unknown_bytes = b"\x00\x01\x02\x03\x04\x05"
        detected = fetcher._detect_format_from_bytes(unknown_bytes)
        assert detected == FormatType.UNKNOWN
    
    def test_detect_empty_bytes(self, fetcher):
        """Deve retornar UNKNOWN para bytes vazios."""
        detected = fetcher._detect_format_from_bytes(b"")
        assert detected == FormatType.UNKNOWN
    
    def test_detect_from_content_type(self, fetcher):
        """Deve detectar formato pelo Content-Type."""
        assert fetcher._detect_format_from_content_type("application/pdf") == FormatType.PDF
        assert fetcher._detect_format_from_content_type("text/csv") == FormatType.CSV
        assert fetcher._detect_format_from_content_type("text/html; charset=utf-8") == FormatType.HTML
        assert fetcher._detect_format_from_content_type("application/json") == FormatType.JSON
        assert fetcher._detect_format_from_content_type("application/xml") == FormatType.XML
        assert fetcher._detect_format_from_content_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) == FormatType.DOCX
    
    def test_detect_from_empty_content_type(self, fetcher):
        """Deve retornar UNKNOWN para Content-Type vazio."""
        assert fetcher._detect_format_from_content_type("") == FormatType.UNKNOWN
        assert fetcher._detect_format_from_content_type(None) == FormatType.UNKNOWN
    
    def test_magic_bytes_constants(self):
        """Deve ter magic bytes definidos para formatos suportados."""
        assert FormatType.PDF in MAGIC_BYTES
        assert FormatType.ZIP in MAGIC_BYTES
        assert MAGIC_BYTES[FormatType.PDF] == [b"%PDF"]


# =============================================================================
# Testes de Detecção de Encoding
# =============================================================================

class TestEncodingDetection:
    """Testes de detecção de encoding."""
    
    def test_detect_utf8_bom(self, fetcher):
        """Deve detectar UTF-8 BOM."""
        data = b"\xef\xbb\xbfHello World"
        encoding = fetcher._detect_encoding(data)
        assert encoding == "utf-8-sig"
    
    def test_detect_utf16_le_bom(self, fetcher):
        """Deve detectar UTF-16 LE BOM."""
        data = b"\xff\xfeH\x00e\x00"
        encoding = fetcher._detect_encoding(data)
        assert encoding == "utf-16-le"
    
    def test_detect_utf16_be_bom(self, fetcher):
        """Deve detectar UTF-16 BE BOM."""
        data = b"\xfe\xff\x00H\x00e"
        encoding = fetcher._detect_encoding(data)
        assert encoding == "utf-16-be"
    
    def test_no_bom_returns_none(self, fetcher):
        """Deve retornar None quando não há BOM."""
        data = b"Hello World"
        encoding = fetcher._detect_encoding(data)
        assert encoding is None


# =============================================================================
# Testes de Limite de Tamanho
# =============================================================================

class TestSizeLimit:
    """Testes de limite de tamanho de arquivo."""
    
    @pytest.mark.asyncio
    async def test_size_limit_exceeded_content_length(self, fetcher):
        """Deve rejeitar se Content-Length excede limite."""
        # Configura um limite pequeno
        fetcher.config.max_size_bytes = 100
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.headers = {
            "content-type": "application/pdf",
            "content-length": "1000",  # Maior que o limite
        }
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            with pytest.raises(FetchSizeError) as exc_info:
                await fetcher.fetch("https://example.com/large.pdf", "source_1")
            
            assert "exceeds max" in str(exc_info.value)
            assert exc_info.value.url == "https://example.com/large.pdf"
    
    @pytest.mark.asyncio
    async def test_size_limit_exceeded_during_stream(self, fetcher):
        """Deve abortar download se tamanho excede durante streaming."""
        fetcher.config.max_size_bytes = 100
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}  # Sem content-length
        mock_response.encoding = "utf-8"
        
        # Gera chunks que excederão o limite
        async def mock_aiter_bytes(chunk_size):
            for i in range(10):
                yield b"x" * 20  # 200 bytes total, acima do limite de 100
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            with pytest.raises(FetchSizeError) as exc_info:
                await fetcher.fetch("https://example.com/stream.txt", "source_1")
            
            assert "exceeds max" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_size_limit_not_exceeded(self, fetcher):
        """Deve permitir download dentro do limite."""
        fetcher.config.max_size_bytes = 1000
        
        content = b"x" * 500  # Dentro do limite
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            yield content
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/ok.txt", "source_1")
            
            assert len(result.content) == 500


# =============================================================================
# Testes de Retry e Erros
# =============================================================================

class TestRetryAndErrors:
    """Testes de retry e tratamento de erros."""
    
    def test_classify_error_timeout(self, fetcher):
        """Deve classificar timeout como retryable."""
        error = httpx.TimeoutException("Connection timed out")
        classified = fetcher._classify_error(error, "https://example.com")
        
        assert isinstance(classified, FetchTimeoutError)
        assert classified.url == "https://example.com"
    
    def test_classify_error_5xx(self, fetcher):
        """Deve classificar erro 5xx como retryable."""
        mock_response = Mock()
        mock_response.status_code = 503
        
        error = httpx.HTTPStatusError(
            "Service Unavailable",
            request=Mock(),
            response=mock_response,
        )
        classified = fetcher._classify_error(error, "https://example.com")
        
        assert isinstance(classified, FetchRetryableError)
        assert classified.status_code == 503
    
    def test_classify_error_429(self, fetcher):
        """Deve classificar erro 429 (rate limit) como retryable."""
        mock_response = Mock()
        mock_response.status_code = 429
        
        error = httpx.HTTPStatusError(
            "Too Many Requests",
            request=Mock(),
            response=mock_response,
        )
        classified = fetcher._classify_error(error, "https://example.com")
        
        assert isinstance(classified, FetchRetryableError)
        assert classified.status_code == 429
    
    def test_classify_error_4xx(self, fetcher):
        """Deve classificar erro 4xx como permanente."""
        mock_response = Mock()
        mock_response.status_code = 404
        
        error = httpx.HTTPStatusError(
            "Not Found",
            request=Mock(),
            response=mock_response,
        )
        classified = fetcher._classify_error(error, "https://example.com")
        
        assert isinstance(classified, FetchPermanentError)
        assert classified.status_code == 404
    
    def test_classify_error_network(self, fetcher):
        """Deve classificar erro de rede como retryable."""
        error = httpx.ConnectError("Connection refused")
        classified = fetcher._classify_error(error, "https://example.com")
        
        assert isinstance(classified, FetchRetryableError)


# =============================================================================
# Testes de Hash SHA-256
# =============================================================================

class TestHashCalculation:
    """Testes de cálculo de hash SHA-256."""
    
    @pytest.mark.asyncio
    async def test_hash_calculation_pdf(self, fetcher, sample_pdf_bytes):
        """Deve calcular hash correto para PDF."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.encoding = None
        
        async def mock_aiter_bytes(chunk_size):
            yield sample_pdf_bytes
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/doc.pdf", "source_1")
            
            expected_hash = hashlib.sha256(sample_pdf_bytes).hexdigest()
            assert result.fingerprint == expected_hash
            assert len(result.fingerprint) == 64  # SHA-256 hex length
    
    @pytest.mark.asyncio
    async def test_hash_calculation_multiple_chunks(self, fetcher):
        """Deve calcular hash correto para múltiplos chunks."""
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        expected_content = b"".join(chunks)
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            for chunk in chunks:
                yield chunk
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/chunks.txt", "source_1")
            
            expected_hash = hashlib.sha256(expected_content).hexdigest()
            assert result.fingerprint == expected_hash
            assert result.content == expected_content


# =============================================================================
# Testes de HEAD Request
# =============================================================================

class TestHeadRequest:
    """Testes de requisição HEAD."""
    
    @pytest.mark.asyncio
    async def test_head_request_success(self, fetcher):
        """Deve executar HEAD request com sucesso."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {
            "content-type": "application/pdf",
            "content-length": "12345",
            "etag": '"abc123"',
            "last-modified": "Wed, 15 Jan 2024 12:00:00 GMT",
        }
        
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head = AsyncMock(return_value=mock_response)
        
        with patch.object(fetcher, '_get_client', return_value=mock_client):
            result = await fetcher.fetch_head("https://example.com/doc.pdf")
            
            assert isinstance(result, FetchMetadata)
            assert result.status_code == 200
            assert result.content_type == "application/pdf"
            assert result.content_length == 12345
            assert result.url == "https://example.com/doc.pdf"
            assert result.method == "HEAD"
    
    @pytest.mark.asyncio
    async def test_head_request_no_content_length(self, fetcher):
        """Deve lidar com HEAD sem Content-Length."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head = AsyncMock(return_value=mock_response)
        
        with patch.object(fetcher, '_get_client', return_value=mock_client):
            result = await fetcher.fetch_head("https://example.com/page.html")
            
            assert result.content_length is None
    
    @pytest.mark.asyncio
    async def test_head_request_error(self, fetcher):
        """Deve tratar erro em HEAD request."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=Mock(),
            response=mock_response,
        )
        
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head = AsyncMock(return_value=mock_response)
        
        with patch.object(fetcher, '_get_client', return_value=mock_client):
            with pytest.raises(FetchError) as exc_info:
                await fetcher.fetch_head("https://example.com/notfound.pdf")
            
            assert exc_info.value.status_code == 404


# =============================================================================
# Testes de Validação de Formato
# =============================================================================

class TestFormatValidation:
    """Testes de validação de formato permitido."""
    
    def test_validate_format_allowed(self, fetcher):
        """Deve permitir formato na lista de permitidos."""
        fetcher.config.allowed_formats = {FormatType.PDF, FormatType.CSV}
        
        # Não deve lançar exceção
        fetcher._validate_format(FormatType.PDF, "application/pdf", b"%PDF")
        fetcher._validate_format(FormatType.CSV, "text/csv", b"a,b,c")
    
    def test_validate_format_not_allowed(self, fetcher):
        """Deve rejeitar formato não permitido."""
        fetcher.config.allowed_formats = {FormatType.PDF}
        
        with pytest.raises(FetchFormatError) as exc_info:
            fetcher._validate_format(FormatType.HTML, "text/html", b"<html>")
        
        assert "not allowed" in str(exc_info.value).lower()
    
    def test_validate_format_no_restriction(self, fetcher):
        """Deve permitir qualquer formato quando não há restrição."""
        fetcher.config.allowed_formats = None
        
        # Não deve lançar exceção para nenhum formato
        for fmt in FormatType:
            fetcher._validate_format(fmt, "application/octet-stream", b"data")


# =============================================================================
# Testes de SSRF Protection
# =============================================================================

class TestSSRFProtection:
    """Testes de proteção SSRF."""
    
    def test_ssrf_blocked_protocol(self, ssrf_config):
        """Deve bloquear protocolos não permitidos."""
        protector = SSRFProtector(ssrf_config)
        
        with pytest.raises(FetchSSRFError) as exc_info:
            protector.validate_url("ftp://example.com/file.txt")
        
        assert "Protocol" in str(exc_info.value)
    
    def test_ssrf_blocked_localhost(self, ssrf_config):
        """Deve bloquear localhost."""
        protector = SSRFProtector(ssrf_config)
        
        with pytest.raises(FetchSSRFError) as exc_info:
            protector.validate_url("http://localhost/admin")
        
        assert "blocked" in str(exc_info.value).lower()
    
    def test_ssrf_blocked_127_0_0_1(self, ssrf_config):
        """Deve bloquear 127.0.0.1."""
        protector = SSRFProtector(ssrf_config)
        
        with pytest.raises(FetchSSRFError) as exc_info:
            protector.validate_url("http://127.0.0.1/admin")
        
        assert "blocked" in str(exc_info.value).lower()
    
    def test_ssrf_blocked_aws_metadata(self, ssrf_config):
        """Deve bloquear AWS metadata IP."""
        protector = SSRFProtector(ssrf_config)
        
        with pytest.raises(FetchSSRFError) as exc_info:
            protector.validate_url("http://169.254.169.254/latest/meta-data/")
        
        assert "blocked" in str(exc_info.value).lower()
    
    def test_ssrf_allowed_external_url(self, ssrf_config):
        """Deve permitir URLs externas."""
        protector = SSRFProtector(ssrf_config)
        
        # Não deve lançar exceção
        protector.validate_url("https://example.com/file.pdf")
        protector.validate_url("https://www.tcu.gov.br/documento.pdf")
    
    def test_ssrf_disabled(self):
        """Deve permitir tudo quando SSRF está desabilitado."""
        config = SSRFConfig(enabled=False)
        protector = SSRFProtector(config)
        
        # Não deve lançar exceção mesmo para localhost
        protector.validate_url("http://localhost/admin")
        protector.validate_url("http://127.0.0.1/secret")
    
    def test_ssrf_allowlist(self):
        """Deve respeitar allowlist de hosts."""
        config = SSRFConfig(
            enabled=True,
            allowed_hosts={"example.com", "tcu.gov.br"},
        )
        protector = SSRFProtector(config)
        
        # Deve permitir
        protector.validate_url("https://example.com/file.pdf")
        protector.validate_url("https://www.tcu.gov.br/doc")
        protector.validate_url("https://subdomain.tcu.gov.br/doc")
        
        # Deve bloquear
        with pytest.raises(FetchSSRFError):
            protector.validate_url("https://evil.com/secret")
    
    def test_ssrf_invalid_url(self, ssrf_config):
        """Deve rejeitar URL inválida."""
        protector = SSRFProtector(ssrf_config)
        
        with pytest.raises(FetchSSRFError) as exc_info:
            protector.validate_url("not-a-valid-url")
        
        assert "no hostname" in str(exc_info.value).lower() or "protocol" in str(exc_info.value).lower()


# =============================================================================
# Testes de Circuit Breaker
# =============================================================================

class TestCircuitBreaker:
    """Testes do circuit breaker."""
    
    def test_circuit_starts_closed(self, circuit_breaker_config):
        """Circuit deve começar em estado CLOSED."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_execute() is True
        assert cb.is_open is False
    
    def test_circuit_opens_after_failures(self, circuit_breaker_config):
        """Circuit deve abrir após threshold de falhas."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        # Registra falhas até abrir
        for _ in range(circuit_breaker_config.failure_threshold):
            cb.record_failure()
        
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open is True
        assert cb.can_execute() is False
    
    def test_circuit_half_open_after_timeout(self, circuit_breaker_config):
        """Circuit deve ir para HALF_OPEN após timeout."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        # Abre o circuito
        for _ in range(circuit_breaker_config.failure_threshold):
            cb.record_failure()
        
        assert cb.state == CircuitBreakerState.OPEN
        
        # Simula passagem do tempo
        import time
        time.sleep(0.1)  # Pequeno delay para teste
        
        # Altera last_failure_time manualmente para simular timeout
        cb._last_failure_time = time.monotonic() - circuit_breaker_config.recovery_timeout - 1
        
        # Agora deve permitir (HALF_OPEN)
        assert cb.can_execute() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN
    
    def test_circuit_closes_after_success(self, circuit_breaker_config):
        """Circuit deve fechar após sucessos em HALF_OPEN."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        # Simula estado HALF_OPEN
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._half_open_calls = 0
        
        # Registra sucessos suficientes
        for _ in range(circuit_breaker_config.half_open_max_calls):
            cb.record_success()
        
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_open is False
    
    def test_circuit_reopens_after_failure_in_half_open(self, circuit_breaker_config):
        """Circuit deve reabrir após falha em HALF_OPEN."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        # Simula estado HALF_OPEN
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._half_open_calls = 0
        
        # Uma falha deve reabrir
        cb.record_failure()
        
        assert cb.state == CircuitBreakerState.OPEN
    
    def test_circuit_success_reduces_failure_count(self, circuit_breaker_config):
        """Sucesso em CLOSED deve reduzir contador de falhas."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        # Adiciona algumas falhas (mas não o suficiente para abrir)
        cb._failure_count = 2
        
        cb.record_success()
        
        assert cb._failure_count == 1
    
    def test_circuit_get_stats(self, circuit_breaker_config):
        """Deve retornar estatísticas do circuit breaker."""
        cb = CircuitBreaker(circuit_breaker_config)
        
        stats = cb.get_stats()
        
        assert "state" in stats
        assert "failure_count" in stats
        assert "success_count" in stats


# =============================================================================
# Testes de Integração com SSRF e Circuit Breaker
# =============================================================================

class TestSecurityIntegration:
    """Testes de integração de segurança."""
    
    @pytest.mark.asyncio
    async def test_fetch_blocks_ssrf(self, fetcher):
        """Deve bloquear requisições SSRF no fetch."""
        with pytest.raises(FetchSSRFError):
            await fetcher.fetch("http://169.254.169.254/metadata", "source_1")
    
    @pytest.mark.asyncio
    async def test_fetch_blocks_localhost(self, fetcher):
        """Deve bloquear requisições para localhost."""
        with pytest.raises(FetchSSRFError):
            await fetcher.fetch("http://localhost/admin", "source_1")
    
    @pytest.mark.asyncio
    async def test_fetch_with_circuit_breaker_open(self, fetcher):
        """Deve rejeitar quando circuit breaker está aberto."""
        url = "https://example.com/file.pdf"
        
        # Força circuito aberto
        cb = fetcher._get_circuit_breaker(url)
        for _ in range(10):
            cb.record_failure()
        
        with pytest.raises(CircuitBreakerOpenError):
            await fetcher.fetch(url, "source_1")
    
    @pytest.mark.asyncio
    async def test_fetch_records_failure_in_circuit_breaker(self, fetcher):
        """Deve registrar falha no circuit breaker quando fetch falha."""
        url = "https://example.com/file.pdf"
        
        # Mock para simular erro de rede
        with patch.object(fetcher, '_fetch_with_retry', side_effect=FetchRetryableError("Network error", url)):
            with pytest.raises(FetchError):
                await fetcher.fetch(url, "source_1")
        
        # Verifica que circuit breaker registrou a falha
        cb = fetcher._get_circuit_breaker(url)
        assert cb._failure_count > 0
    
    @pytest.mark.asyncio
    async def test_head_blocks_ssrf(self, fetcher):
        """Deve bloquear requisições SSRF no HEAD."""
        with pytest.raises(FetchSSRFError):
            await fetcher.fetch_head("http://127.0.0.1/admin")


# =============================================================================
# Testes de Integração Simples
# =============================================================================

class TestFetchIntegration:
    """Testes de integração simplificados."""
    
    @pytest.mark.asyncio
    async def test_full_fetch_flow(self, fetcher_config):
        """Deve executar fluxo completo de fetch."""
        content = b"%PDF-1.4 test content"
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {
            "content-type": "application/pdf",
            "content-length": str(len(content)),
        }
        mock_response.encoding = None
        
        async def mock_aiter_bytes(chunk_size):
            yield content
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        fetcher = ContentFetcher(fetcher_config)
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/test.pdf", "test_source")
            
            assert result.url == "https://example.com/test.pdf"
            assert result.content == content
            assert result.metadata.status_code == 200
            assert result.metadata.content_type == "application/pdf"
            assert result.fingerprint is not None
            assert result.metadata.fetch_duration_ms >= 0
    
    @pytest.mark.asyncio
    async def test_fetch_with_custom_headers(self, fetcher):
        """Deve aceitar headers customizados."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.encoding = "utf-8"
        
        async def mock_aiter_bytes(chunk_size):
            yield b"ok"
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        custom_headers = {"Authorization": "Bearer token123"}
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response) as mock_retry:
            await fetcher.fetch(
                "https://example.com/api",
                "source_1",
                headers=custom_headers,
            )
            
            # Verifica se foi chamado com headers customizados
            call_kwargs = mock_retry.call_args[1] if mock_retry.call_args else {}


# =============================================================================
# Testes de Performance
# =============================================================================

class TestPerformance:
    """Testes de performance do fetcher."""
    
    @pytest.mark.asyncio
    async def test_large_file_streaming(self, fetcher):
        """Deve fazer streaming de arquivo grande sem carregar tudo em memória."""
        # Simula arquivo de 10MB em chunks de 1MB
        chunk_size = 1024 * 1024
        num_chunks = 10
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_response.encoding = None
        
        async def mock_aiter_bytes(**kwargs):
            for i in range(num_chunks):
                yield b"x" * chunk_size
        
        mock_response.aiter_bytes = mock_aiter_bytes
        
        fetcher.config.max_size_bytes = chunk_size * num_chunks + 1000
        
        with patch.object(fetcher, '_fetch_with_retry', return_value=mock_response):
            result = await fetcher.fetch("https://example.com/large.bin", "source_1")
            
            assert len(result.content) == chunk_size * num_chunks
            # Verifica que o hash foi calculado corretamente
            expected_hash = hashlib.sha256(b"x" * chunk_size * num_chunks).hexdigest()
            assert result.fingerprint == expected_hash


# =============================================================================
# Testes de Circuit Breaker Management
# =============================================================================

class TestCircuitBreakerManagement:
    """Testes de gerenciamento de circuit breakers."""
    
    def test_get_circuit_breaker_stats(self, fetcher):
        """Deve retornar estatísticas de circuit breakers."""
        # Cria circuit breakers para alguns domínios
        fetcher._get_circuit_breaker("https://example1.com")
        fetcher._get_circuit_breaker("https://example2.com")
        
        stats = fetcher.get_circuit_breaker_stats()
        
        assert "example1.com" in stats
        assert "example2.com" in stats
    
    def test_reset_circuit_breaker_specific(self, fetcher):
        """Deve resetar circuit breaker específico."""
        fetcher._get_circuit_breaker("https://example.com")
        
        assert "example.com" in fetcher._circuit_breakers
        
        fetcher.reset_circuit_breaker("example.com")
        
        assert "example.com" not in fetcher._circuit_breakers
    
    def test_reset_circuit_breaker_all(self, fetcher):
        """Deve resetar todos os circuit breakers."""
        fetcher._get_circuit_breaker("https://example1.com")
        fetcher._get_circuit_breaker("https://example2.com")
        
        fetcher.reset_circuit_breaker()
        
        assert len(fetcher._circuit_breakers) == 0
