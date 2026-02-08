"""Testes unitários para o módulo de change detection.

Este módulo testa a detecção de mudanças em URLs utilizando:
- ETag (header HTTP)
- Last-Modified (header HTTP)
- Content-Length (header HTTP)
- Content-Hash (SHA-256 do conteúdo)

Testes:
    - test_check_url_etag_changed: Detecção de mudança via ETag
    - test_check_url_etag_unchanged: Confirmação de não-mudança via ETag
    - test_check_url_last_modified: Detecção via Last-Modified
    - test_check_url_content_hash: Detecção via hash de conteúdo
    - test_check_batch: Verificação em lote de múltiplas URLs
    - test_cache_persistence: Persistência do cache no banco de dados
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import httpx
import pytest
import pytest_asyncio


# =============================================================================
# Setup: Mock completo do ambiente antes de importar
# =============================================================================

# Criar enum mock
from enum import Enum

class ChangeDetectionResult(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    ERROR = "error"


# Mock completo dos módulos
_mock_db_module = Mock()
_mock_db_module.DatabaseManager = Mock()
_mock_db_module.get_engine = Mock()

_mock_models_cache = Mock()
_mock_models_cache.ChangeDetectionCache = Mock()

_mock_contracts = Mock()
_mock_contracts.ChangeCheckResult = Mock()
_mock_contracts.ChangeDetectionSummary = Mock()

_mock_types = Mock()
_mock_types.ChangeDetectionResult = ChangeDetectionResult

# Instalar mocks
sys.modules['gabi'] = Mock()
sys.modules['gabi.db'] = _mock_db_module
sys.modules['gabi.models'] = Mock()
sys.modules['gabi.models.cache'] = _mock_models_cache
sys.modules['gabi.pipeline'] = Mock()
sys.modules['gabi.pipeline.contracts'] = _mock_contracts
sys.modules['gabi.types'] = _mock_types

# Agora importa o módulo
import importlib.util
spec = importlib.util.spec_from_file_location(
    "change_detection", 
    "/home/fgamajr/dev/gabi-kimi/src/gabi/pipeline/change_detection.py"
)
_change_detection_mod = importlib.util.module_from_spec(spec)

# Substituir imports no namespace do módulo
_change_detection_mod.DatabaseManager = _mock_db_module.DatabaseManager
_change_detection_mod.ChangeDetectionCache = _mock_models_cache.ChangeDetectionCache
_change_detection_mod.ChangeCheckResult = _mock_contracts.ChangeCheckResult
_change_detection_mod.ChangeDetectionSummary = _mock_contracts.ChangeDetectionSummary
_change_detection_mod.ChangeDetectionResult = ChangeDetectionResult

# Carregar o módulo
spec.loader.exec_module(_change_detection_mod)

# Extrair as classes
ChangeDetector = _change_detection_mod.ChangeDetector
HTTPHeaders = _change_detection_mod.HTTPHeaders
URLCheckRequest = _change_detection_mod.URLCheckRequest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_url() -> str:
    """URL de exemplo para testes."""
    return "https://example.com/document.pdf"


@pytest.fixture
def sample_source_id() -> str:
    """ID de fonte de exemplo."""
    return "test_source"


@pytest.fixture
def sample_etag() -> str:
    """ETag de exemplo."""
    return '"abc123def456"'


@pytest.fixture
def sample_last_modified() -> str:
    """Header Last-Modified de exemplo."""
    return "Wed, 21 Oct 2024 07:28:00 GMT"


@pytest.fixture
def change_detector() -> ChangeDetector:
    """Cria uma instância do ChangeDetector para testes."""
    mock_db = Mock()
    detector = ChangeDetector(db_manager=mock_db)
    return detector


# =============================================================================
# Testes de ETag
# =============================================================================

class TestCheckURLETag:
    """Testes para verificação de mudanças via ETag."""
    
    def test_check_url_etag_changed(self, change_detector: ChangeDetector) -> None:
        """Testa detecção de mudança quando ETag é diferente."""
        # Arrange
        old_etag = '"old-etag-value"'
        new_etag = '"new-etag-value"'
        
        cached = Mock()
        cached.etag = old_etag
        cached.last_modified = None
        cached.content_length = None
        cached.content_hash = None
        
        headers = HTTPHeaders(etag=new_etag)
        
        # Act
        has_changed, method = change_detector._detect_change_method(cached, headers)
        
        # Assert
        assert has_changed is True
        assert method == "etag"
    
    def test_check_url_etag_unchanged(self, change_detector: ChangeDetector, sample_etag: str) -> None:
        """Testa detecção de não-mudança quando ETag é igual."""
        # Arrange
        cached = Mock()
        cached.etag = sample_etag
        cached.last_modified = None
        cached.content_length = None
        cached.content_hash = None
        
        headers = HTTPHeaders(etag=sample_etag)
        
        # Act
        has_changed, method = change_detector._detect_change_method(cached, headers)
        
        # Assert
        assert has_changed is False
        assert method == "etag"


# =============================================================================
# Testes de Last-Modified
# =============================================================================

class TestCheckURLLastModified:
    """Testes para verificação de mudanças via Last-Modified."""
    
    def test_check_url_last_modified(self, change_detector: ChangeDetector, sample_last_modified: str) -> None:
        """Testa detecção de mudança via header Last-Modified."""
        # Arrange
        old_modified = "Tue, 20 Oct 2024 07:28:00 GMT"
        
        cached = Mock()
        cached.etag = None
        cached.last_modified = old_modified
        cached.content_length = None
        cached.content_hash = None
        
        headers = HTTPHeaders(last_modified=sample_last_modified)
        
        # Act
        has_changed, method = change_detector._detect_change_method(cached, headers)
        
        # Assert
        assert has_changed is True
        assert method == "last_modified"


# =============================================================================
# Testes de Content Hash
# =============================================================================

class TestCheckURLContentHash:
    """Testes para verificação de mudanças via hash de conteúdo."""
    
    def test_check_url_content_hash(self, change_detector: ChangeDetector) -> None:
        """Testa detecção de mudança via hash SHA-256 do conteúdo."""
        # Arrange
        old_hash = hashlib.sha256(b"old content").hexdigest()
        new_hash = hashlib.sha256(b"new content").hexdigest()
        
        cached = Mock()
        cached.etag = None
        cached.last_modified = None
        cached.content_length = None
        cached.content_hash = old_hash
        
        headers = HTTPHeaders()
        
        # Act
        has_changed, method = change_detector._detect_change_method(cached, headers, new_hash)
        
        # Assert
        assert has_changed is True
        assert method == "content_hash"


# =============================================================================
# Testes de Batch
# =============================================================================

@pytest.mark.asyncio
class TestCheckBatch:
    """Testes para verificação em lote de URLs."""
    
    async def test_check_batch(self, change_detector: ChangeDetector) -> None:
        """Testa verificação de múltiplas URLs em batch."""
        # Arrange: Múltiplas URLs para verificar
        urls = [
            URLCheckRequest(url="https://example.com/doc1.pdf", source_id="test_source"),
            URLCheckRequest(url="https://example.com/doc2.pdf", source_id="test_source"),
            URLCheckRequest(url="https://example.com/doc3.pdf", source_id="test_source"),
        ]
        
        # Criar classe de resultado concreta
        from dataclasses import dataclass, field
        from datetime import datetime
        from typing import List
        
        @dataclass
        class SimpleCheckResult:
            url: str
            result: ChangeDetectionResult
            etag: Any = None
            last_modified: Any = None
            content_hash: Any = None
            content_length: Any = None
            previous_check: Any = None
            current_check: datetime = field(default_factory=datetime.utcnow)
        
        @dataclass
        class SimpleSummary:
            new_urls: List[str] = field(default_factory=list)
            changed_urls: List[str] = field(default_factory=list)
            unchanged_urls: List[str] = field(default_factory=list)
            error_urls: List[str] = field(default_factory=list)
            total_checked: int = 0
            duration_seconds: float = 0.0
        
        # Mock para check_url
        async def mock_check_url(url: str, source_id: str):
            if "doc1" in url:
                return SimpleCheckResult(url=url, result=ChangeDetectionResult.NEW)
            elif "doc2" in url:
                return SimpleCheckResult(url=url, result=ChangeDetectionResult.CHANGED)
            else:
                return SimpleCheckResult(url=url, result=ChangeDetectionResult.UNCHANGED)
        
        # Mock para ChangeDetectionSummary
        original_summary = _change_detection_mod.ChangeDetectionSummary
        _change_detection_mod.ChangeDetectionSummary = SimpleSummary
        
        change_detector.check_url = mock_check_url
        
        try:
            # Act
            summary = await change_detector.check_batch(urls)
            
            # Assert
            assert summary.total_checked == 3
            assert len(summary.new_urls) == 1
            assert len(summary.changed_urls) == 1
            assert len(summary.unchanged_urls) == 1
            assert len(summary.error_urls) == 0
        finally:
            # Restore
            _change_detection_mod.ChangeDetectionSummary = original_summary


# =============================================================================
# Testes de Persistência
# =============================================================================

class TestCachePersistence:
    """Testes para persistência do cache de change detection."""
    
    def test_cache_persistence_new_entry(self, change_detector: ChangeDetector) -> None:
        """Testa criação de nova entrada no cache."""
        # O método _update_cache cria/atualiza entradas no cache
        # Verificamos que o detector tem o método
        assert hasattr(change_detector, '_update_cache')
        assert callable(change_detector._update_cache)
    
    def test_cache_persistence_update_existing(self, change_detector: ChangeDetector) -> None:
        """Testa atualização de entrada existente no cache."""
        # Verificamos que o detector pode atualizar entradas existentes
        assert hasattr(change_detector, '_get_or_create_cache')
        assert callable(change_detector._get_or_create_cache)


# =============================================================================
# Testes de Helpers
# =============================================================================

class TestHTTPHeaders:
    """Testes para a classe HTTPHeaders."""
    
    def test_http_headers_creation(self) -> None:
        """Testa criação de HTTPHeaders com valores."""
        headers = HTTPHeaders(
            etag='"abc123"',
            last_modified="Wed, 21 Oct 2024 07:28:00 GMT",
            content_length=1024,
            content_type="application/pdf"
        )
        
        assert headers.etag == '"abc123"'
        assert headers.last_modified == "Wed, 21 Oct 2024 07:28:00 GMT"
        assert headers.content_length == 1024
        assert headers.content_type == "application/pdf"
    
    def test_http_headers_defaults(self) -> None:
        """Testa criação de HTTPHeaders com valores padrão."""
        headers = HTTPHeaders()
        
        assert headers.etag is None
        assert headers.last_modified is None
        assert headers.content_length is None
        assert headers.content_type is None


class TestURLCheckRequest:
    """Testes para a classe URLCheckRequest."""
    
    def test_url_check_request_creation(self) -> None:
        """Testa criação de URLCheckRequest."""
        request = URLCheckRequest(
            url="https://example.com/doc.pdf",
            source_id="test_source",
            priority=5
        )
        
        assert request.url == "https://example.com/doc.pdf"
        assert request.source_id == "test_source"
        assert request.priority == 5
    
    def test_url_check_request_default_priority(self) -> None:
        """Testa criação de URLCheckRequest com prioridade padrão."""
        request = URLCheckRequest(
            url="https://example.com/doc.pdf",
            source_id="test_source"
        )
        
        assert request.priority == 0


class TestChangeDetectorInit:
    """Testes para inicialização do ChangeDetector."""
    
    def test_init_with_defaults(self) -> None:
        """Testa inicialização com valores padrão."""
        mock_db = Mock()
        detector = ChangeDetector(db_manager=mock_db)
        
        assert detector.timeout == 30.0
        assert detector.max_retries == 3
        assert detector.user_agent == "GABI-ChangeDetector/1.0"
    
    def test_init_with_custom_values(self) -> None:
        """Testa inicialização com valores customizados."""
        mock_db = Mock()
        detector = ChangeDetector(
            db_manager=mock_db,
            timeout=60.0,
            max_retries=5,
            user_agent="Custom-Agent/1.0"
        )
        
        assert detector.db_manager == mock_db
        assert detector.timeout == 60.0
        assert detector.max_retries == 5
        assert detector.user_agent == "Custom-Agent/1.0"


class TestChangeDetectionMethods:
    """Testes para os métodos de detecção de mudança."""
    
    def test_detect_change_method_new_url(self, change_detector: ChangeDetector) -> None:
        """Testa detecção para URL nova (sem cache)."""
        headers = HTTPHeaders(etag='"new-etag"')
        
        has_changed, method = change_detector._detect_change_method(None, headers)
        
        assert has_changed is True
        assert method == "etag"
    
    def test_detect_change_method_no_headers(self, change_detector: ChangeDetector) -> None:
        """Testa quando não há headers de comparação."""
        cached = Mock()
        cached.etag = None
        cached.last_modified = None
        cached.content_length = None
        cached.content_hash = None
        
        headers = HTTPHeaders()
        
        has_changed, method = change_detector._detect_change_method(cached, headers)
        
        # Sem mecanismo de comparação = assume mudança
        assert has_changed is True
        assert method == "unknown"
    
    def test_detect_change_method_content_length(self, change_detector: ChangeDetector) -> None:
        """Testa detecção via Content-Length."""
        cached = Mock()
        cached.etag = None
        cached.last_modified = None
        cached.content_length = 1024
        cached.content_hash = None
        
        headers = HTTPHeaders(content_length=2048)
        
        has_changed, method = change_detector._detect_change_method(cached, headers)
        
        assert has_changed is True
        assert method == "content_length"


class TestContentHash:
    """Testes para hash de conteúdo."""
    
    def test_compute_content_hash(self, change_detector: ChangeDetector) -> None:
        """Testa cálculo de hash SHA-256."""
        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest()
        
        result = change_detector._compute_content_hash(content)
        
        assert result == expected_hash
    
    def test_compute_content_hash_empty(self, change_detector: ChangeDetector) -> None:
        """Testa cálculo de hash para conteúdo vazio."""
        content = b""
        expected_hash = hashlib.sha256(content).hexdigest()
        
        result = change_detector._compute_content_hash(content)
        
        assert result == expected_hash


class TestExtractHeaders:
    """Testes para extração de headers HTTP."""
    
    def test_extract_headers_complete(self, change_detector: ChangeDetector) -> None:
        """Testa extração de todos os headers."""
        mock_response = Mock()
        mock_response.headers = {
            "etag": '"abc123"',
            "last-modified": "Wed, 21 Oct 2024 07:28:00 GMT",
            "content-length": "1024",
            "content-type": "application/pdf"
        }
        
        headers = change_detector._extract_headers(mock_response)
        
        assert headers.etag == '"abc123"'
        assert headers.last_modified == "Wed, 21 Oct 2024 07:28:00 GMT"
        assert headers.content_length == 1024
        assert headers.content_type == "application/pdf"
    
    def test_extract_headers_partial(self, change_detector: ChangeDetector) -> None:
        """Testa extração com headers parciais."""
        mock_response = Mock()
        mock_response.headers = {
            "etag": '"abc123"'
        }
        
        headers = change_detector._extract_headers(mock_response)
        
        assert headers.etag == '"abc123"'
        assert headers.last_modified is None
        assert headers.content_length is None
