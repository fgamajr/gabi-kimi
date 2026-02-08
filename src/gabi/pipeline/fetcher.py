"""Fetcher module para download de conteúdo.

Implementa a fase de fetch do pipeline de ingestão com:
- HTTP GET com streaming para arquivos grandes
- Validação de magic bytes
- Cálculo de hash SHA-256
- Retry com exponential backoff
- Limite de tamanho de arquivo
- Timeout configurável
- True streaming para arquivos grandes (disco temporário)
- Proteção SSRF (Server-Side Request Forgery)
- Circuit breaker para prevenir falhas em cascata

Security Features:
- SSRF Protection: Bloqueia IPs internos (169.254.169.254, 10.0.0.0/8, etc.)
- Protocol restrictions: Apenas http/https permitido
- DNS rebinding protection: Validação de IP após DNS resolution
- URL allowlist/blocklist: Controle de domínios permitidos
"""

import hashlib
import ipaddress
import logging
import os
import re
import socket
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set, TypeVar
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from gabi.config import settings
from gabi.pipeline.contracts import FetchMetadata, FetchedContent


logger = logging.getLogger(__name__)

T = TypeVar("T")


class FormatType(str, Enum):
    """Tipos de formato detectados por magic bytes."""
    PDF = "pdf"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    XML = "xml"
    ZIP = "zip"
    DOCX = "docx"  # Office Open XML Document
    XLSX = "xlsx"  # Office Open XML Spreadsheet
    PPTX = "pptx"  # Office Open XML Presentation
    ODT = "odt"    # OpenDocument Text
    ODS = "ods"    # OpenDocument Spreadsheet
    ODP = "odp"    # OpenDocument Presentation
    TXT = "txt"    # Plain text
    UNKNOWN = "unknown"


# Magic bytes para detecção de formato
MAGIC_BYTES: Dict[FormatType, list[bytes]] = {
    FormatType.PDF: [b"%PDF"],
    FormatType.ZIP: [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"],
}

# MIME types para detecção de formato
MIME_TYPE_MAP: Dict[str, FormatType] = {
    "application/pdf": FormatType.PDF,
    "text/csv": FormatType.CSV,
    "text/html": FormatType.HTML,
    "application/html": FormatType.HTML,
    "application/json": FormatType.JSON,
    "text/json": FormatType.JSON,
    "application/xml": FormatType.XML,
    "text/xml": FormatType.XML,
    "application/zip": FormatType.ZIP,
    "application/octet-stream": FormatType.UNKNOWN,
    # Office Open XML
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FormatType.DOCX,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FormatType.XLSX,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": FormatType.PPTX,
    # OpenDocument
    "application/vnd.oasis.opendocument.text": FormatType.ODT,
    "application/vnd.oasis.opendocument.spreadsheet": FormatType.ODS,
    "application/vnd.oasis.opendocument.presentation": FormatType.ODP,
    # Text
    "text/plain": FormatType.TXT,
}

# Encoding detection patterns
ENCODING_BOMS = {
    "utf-8-sig": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}


class FetchError(Exception):
    """Erro base para operações de fetch."""
    
    def __init__(self, message: str, url: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class FetchTimeoutError(FetchError):
    """Erro quando o fetch excede o timeout."""
    pass


class FetchSizeError(FetchError):
    """Erro quando o arquivo excede o tamanho máximo permitido."""
    pass


class FetchFormatError(FetchError):
    """Erro quando o formato do arquivo não é suportado ou inválido."""
    pass


class FetchRetryableError(FetchError):
    """Erro que pode ser tentado novamente (5xx, timeouts de rede, etc)."""
    pass


class FetchPermanentError(FetchError):
    """Erro permanente que não deve ser tentado novamente (4xx)."""
    pass


class FetchSSRFError(FetchPermanentError):
    """Erro de segurança SSRF - tentativa de acesso a recurso interno bloqueado."""
    pass


class CircuitBreakerState(Enum):
    """Estados do Circuit Breaker."""
    CLOSED = "closed"      # Operação normal
    OPEN = "open"          # Falhando, rejeitando requests
    HALF_OPEN = "half_open"  # Testando se serviço recuperou


class CircuitBreakerOpenError(FetchError):
    """Circuit breaker está aberto para um domínio."""
    pass


@dataclass
class CircuitBreakerConfig:
    """Configuração do Circuit Breaker.
    
    Attributes:
        failure_threshold: Número de falhas antes de abrir
        recovery_timeout: Tempo em segundos antes de tentar recovery
        half_open_max_calls: Máximo de calls em half-open
    """
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3


@dataclass
class SSRFConfig:
    """Configuração de proteção SSRF.
    
    Attributes:
        enabled: Se a proteção SSRF está habilitada
        blocked_hosts: Lista de hosts/IP bloqueados
        blocked_cidr: Lista de CIDRs bloqueados (ex: 10.0.0.0/8)
        allowed_hosts: Lista de hosts permitidos (se vazio, todos permitidos exceto bloqueados)
        allowed_protocols: Protocolos permitidos
        block_internal_ips: Se deve bloquear IPs privados automaticamente
        dns_rebinding_protection: Se deve habilitar proteção contra DNS rebinding
    """
    enabled: bool = True
    blocked_hosts: Set[str] = field(default_factory=lambda: {
        "169.254.169.254",  # AWS metadata
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
    })
    blocked_cidr: Set[str] = field(default_factory=lambda: {
        "10.0.0.0/8",      # RFC1918 - Private
        "172.16.0.0/12",   # RFC1918 - Private
        "192.168.0.0/16",  # RFC1918 - Private
        "127.0.0.0/8",     # Loopback
        "169.254.0.0/16",  # Link-local
        "::1/128",         # IPv6 Loopback
        "fe80::/10",       # IPv6 Link-local
        "fc00::/7",        # IPv6 Unique Local
    })
    allowed_hosts: Set[str] = field(default_factory=set)
    allowed_protocols: Set[str] = field(default_factory=lambda: {"http", "https"})
    block_internal_ips: bool = True
    dns_rebinding_protection: bool = True
    
    def __post_init__(self):
        """Valida e normaliza a configuração."""
        # Normaliza blocked_hosts para lowercase
        self.blocked_hosts = {h.lower() for h in self.blocked_hosts}
        # Normaliza allowed_hosts para lowercase se não estiver vazio
        if self.allowed_hosts:
            self.allowed_hosts = {h.lower() for h in self.allowed_hosts}
        # Normaliza allowed_protocols para lowercase
        self.allowed_protocols = {p.lower() for p in self.allowed_protocols}


@dataclass
class FetcherConfig:
    """Configuração para o ContentFetcher.
    
    Attributes:
        timeout: Timeout da requisição em segundos
        max_retries: Número máximo de tentativas
        max_size_bytes: Tamanho máximo do arquivo em bytes
        chunk_size: Tamanho do chunk para streaming
        validate_magic_bytes: Se deve validar magic bytes
        allowed_formats: Formatos permitidos (None = todos)
        headers: Headers HTTP adicionais
        stream_threshold: Limite para streaming em disco (bytes)
        ssrf_config: Configuração de proteção SSRF
        circuit_breaker_config: Configuração do circuit breaker
    """
    timeout: int = field(default_factory=lambda: settings.pipeline_fetch_timeout)
    max_retries: int = field(default_factory=lambda: settings.pipeline_fetch_max_retries)
    max_size_bytes: int = field(default_factory=lambda: settings.pipeline_fetch_max_size_mb * 1024 * 1024)
    chunk_size: int = 8192  # 8KB
    validate_magic_bytes: bool = True
    allowed_formats: Optional[Set[FormatType]] = None
    headers: Dict[str, str] = field(default_factory=dict)
    stream_threshold: Optional[int] = None  # None = 10MB or max_size_bytes, whichever is smaller
    ssrf_config: Optional[SSRFConfig] = None
    circuit_breaker_config: Optional[CircuitBreakerConfig] = None
    
    def __post_init__(self):
        """Valida a configuração após inicialização."""
        # Set default stream_threshold if not provided
        if self.stream_threshold is None:
            default_threshold = 10 * 1024 * 1024  # 10MB
            self.stream_threshold = min(default_threshold, self.max_size_bytes)
        
        self.validate()
    
    def validate(self) -> None:
        """Valida as configurações do fetcher.
        
        Raises:
            ValueError: Se alguma configuração for inválida
        """
        if self.timeout < 1 or self.timeout > 600:
            raise ValueError(f"timeout must be between 1 and 600 seconds, got {self.timeout}")
        
        if self.max_retries < 0 or self.max_retries > 10:
            raise ValueError(f"max_retries must be between 0 and 10, got {self.max_retries}")
        
        if self.max_size_bytes < 1024 or self.max_size_bytes > 10 * 1024 * 1024 * 1024:
            raise ValueError(f"max_size_bytes must be between 1KB and 10GB, got {self.max_size_bytes}")
        
        if self.chunk_size < 1024 or self.chunk_size > 1024 * 1024:
            raise ValueError(f"chunk_size must be between 1KB and 1MB, got {self.chunk_size}")
        
        if self.stream_threshold < 1024 or self.stream_threshold > self.max_size_bytes:
            raise ValueError(f"stream_threshold must be between 1KB and max_size_bytes, got {self.stream_threshold}")
        
        # Inicializa SSRF config se não fornecida
        if self.ssrf_config is None:
            self.ssrf_config = SSRFConfig()
        
        # Inicializa circuit breaker config se não fornecida
        if self.circuit_breaker_config is None:
            self.circuit_breaker_config = CircuitBreakerConfig()


class CircuitBreaker:
    """Circuit Breaker para proteger contra falhas em cascata.
    
    Implementa padrão Circuit Breaker com estados:
    - CLOSED: Operação normal, passa requests
    - OPEN: Rejeita requests rapidamente
    - HALF_OPEN: Testa se serviço recuperou
    
    Cada domínio tem seu próprio circuit breaker.
    """
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._last_state_change = time.monotonic()
    
    @property
    def state(self) -> CircuitBreakerState:
        """Retorna estado atual do circuit breaker."""
        return self._state
    
    @property
    def is_open(self) -> bool:
        """Verifica se circuit breaker está aberto."""
        return self._state == CircuitBreakerState.OPEN
    
    def can_execute(self) -> bool:
        """Verifica se pode executar request."""
        if self._state == CircuitBreakerState.CLOSED:
            return True
        
        if self._state == CircuitBreakerState.OPEN:
            # Verifica se passou tempo suficiente para tentar recovery
            if self._last_failure_time:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.config.recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
                    self._last_state_change = time.monotonic()
                    logger.info(f"Circuit breaker transitioning to HALF_OPEN")
                    return True
            return False
        
        # HALF_OPEN
        return self._half_open_calls < self.config.half_open_max_calls
    
    def record_success(self) -> None:
        """Registra sucesso."""
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.half_open_max_calls:
                logger.info(f"Circuit breaker transitioning to CLOSED")
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                self._last_state_change = time.monotonic()
        else:
            self._failure_count = max(0, self._failure_count - 1)
    
    def record_failure(self) -> None:
        """Registra falha."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        
        if self._state == CircuitBreakerState.HALF_OPEN:
            logger.warning(f"Circuit breaker transitioning to OPEN (failure in half-open)")
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = time.monotonic()
        elif self._failure_count >= self.config.failure_threshold:
            if self._state != CircuitBreakerState.OPEN:
                logger.warning(f"Circuit breaker transitioning to OPEN ({self._failure_count} failures)")
                self._state = CircuitBreakerState.OPEN
                self._last_state_change = time.monotonic()
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do circuit breaker."""
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
            "last_state_change": self._last_state_change,
        }


class SSRFProtector:
    """Proteção contra SSRF (Server-Side Request Forgery).
    
    Implementa múltiplas camadas de proteção:
    1. Validação de URL (protocolo, formato)
    2. Bloqueio de hosts/CIDRs específicos
    3. Validação de IP após DNS resolution (DNS rebinding protection)
    4. Allowlist de domínios permitidos
    """
    
    def __init__(self, config: SSRFConfig):
        self.config = config
        self._cidr_networks = self._parse_cidrs(config.blocked_cidr)
    
    def _parse_cidrs(self, cidrs: Set[str]) -> list:
        """Parse CIDR strings para objetos ipaddress."""
        networks = []
        for cidr in cidrs:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError as e:
                logger.warning(f"Invalid CIDR {cidr}: {e}")
        return networks
    
    def validate_url(self, url: str) -> None:
        """Valida URL contra ataques SSRF.
        
        Args:
            url: URL a ser validada
            
        Raises:
            FetchSSRFError: Se URL for potencialmente perigosa
        """
        if not self.config.enabled:
            return
        
        # Parse URL
        parsed = urlparse(url)
        
        # Valida protocolo
        protocol = parsed.scheme.lower()
        if protocol not in self.config.allowed_protocols:
            raise FetchSSRFError(
                f"Protocol '{protocol}' not allowed. Allowed: {self.config.allowed_protocols}",
                url
            )
        
        # Extrai host
        host = parsed.hostname
        if not host:
            raise FetchSSRFError("Invalid URL: no hostname", url)
        
        host_lower = host.lower()
        
        # Verifica allowlist
        if self.config.allowed_hosts:
            # Extrai domínio base para matching
            domain_parts = host_lower.split('.')
            is_allowed = False
            for allowed in self.config.allowed_hosts:
                if host_lower == allowed or host_lower.endswith('.' + allowed):
                    is_allowed = True
                    break
            if not is_allowed:
                raise FetchSSRFError(
                    f"Host '{host}' not in allowlist",
                    url
                )
        
        # Verifica blocked hosts exatos
        if host_lower in self.config.blocked_hosts:
            raise FetchSSRFError(
                f"Host '{host}' is blocked",
                url
            )
        
        # Tenta resolver o host para verificar IPs
        try:
            # Resolve para IPv4 e IPv6
            addr_info = socket.getaddrinfo(host, None)
            
            for info in addr_info:
                ip_str = info[4][0]
                if self._is_blocked_ip(ip_str):
                    raise FetchSSRFError(
                        f"IP {ip_str} (resolved from {host}) is in blocked range",
                        url
                    )
        except socket.gaierror:
            # Não conseguiu resolver - pode ser um domínio inválido
            # Mas não necessariamente malicioso, deixa passar para o HTTP client lidar
            pass
        except FetchSSRFError:
            raise
        except Exception as e:
            logger.warning(f"Error during SSRF validation for {url}: {e}")
    
    def _is_blocked_ip(self, ip_str: str) -> bool:
        """Verifica se IP está em range bloqueado.
        
        Args:
            ip_str: Endereço IP como string
            
        Returns:
            True se IP está bloqueado
        """
        try:
            ip = ipaddress.ip_address(ip_str)
            
            # Verifica se é IP privado/link-local (se configurado)
            if self.config.block_internal_ips:
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return True
                # Verifica IPv6 unique local
                if isinstance(ip, ipaddress.IPv6Address):
                    if ip_str.startswith("fc") or ip_str.startswith("fd"):
                        return True
            
            # Verifica CIDRs específicos
            for network in self._cidr_networks:
                if ip in network:
                    return True
            
            return False
        except ValueError:
            # IP inválido
            return True


class ContentFetcher:
    """Fetcher de conteúdo com streaming, retry e validação.
    
    Responsável por baixar conteúdo de URLs com as seguintes características:
    - Streaming para arquivos grandes (não carrega tudo em memória)
    - Retry com exponential backoff para erros transitórios
    - Validação de magic bytes para detectar formato real
    - Limite de tamanho para prevenir OOM/DoS
    - Cálculo de hash SHA-256 para integridade
    - Proteção SSRF contra ataques
    - Circuit breaker para prevenir falhas em cascata
    
    Example:
        >>> fetcher = ContentFetcher()
        >>> result = await fetcher.fetch("https://example.com/doc.pdf", "source_1")
        >>> print(f"Downloaded {result.size_bytes} bytes, format: {result.detected_format}")
    """
    
    DEFAULT_HEADERS = {
        "User-Agent": "GABI-Pipeline/1.0 (TCU Data Ingestion Bot)",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    
    def __init__(self, config: Optional[FetcherConfig] = None):
        """Inicializa o fetcher.
        
        Args:
            config: Configuração opcional (usa padrão se não fornecida)
        """
        self.config = config or FetcherConfig()
        self.config.validate()
        
        self._client: Optional[httpx.AsyncClient] = None
        self._ssrf_protector = SSRFProtector(self.config.ssrf_config)
        
        # Circuit breakers por domínio
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def _get_circuit_breaker(self, url: str) -> CircuitBreaker:
        """Obtém ou cria circuit breaker para um domínio.
        
        Args:
            url: URL para extrair domínio
            
        Returns:
            CircuitBreaker para o domínio
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        if domain not in self._circuit_breakers:
            self._circuit_breakers[domain] = CircuitBreaker(self.config.circuit_breaker_config)
        
        return self._circuit_breakers[domain]
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Obtém ou cria o cliente HTTP."""
        if self._client is None or self._client.is_closed:
            headers = {**self.DEFAULT_HEADERS, **self.config.headers}
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout),
                follow_redirects=True,
                max_redirects=10,
            )
        return self._client
    
    async def close(self):
        """Fecha o cliente HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
    
    def _detect_encoding(self, data: bytes) -> Optional[str]:
        """Detecta encoding por BOM (Byte Order Mark).
        
        Args:
            data: Primeiros bytes do arquivo
            
        Returns:
            Nome do encoding ou None
        """
        for encoding, bom in ENCODING_BOMS.items():
            if data.startswith(bom):
                return encoding
        return None
    
    def _detect_office_format(self, data: bytes) -> Optional[FormatType]:
        """Detecta formato Office (DOCX, XLSX, PPTX) de arquivo ZIP.
        
        Args:
            data: Primeiros bytes do arquivo ZIP
            
        Returns:
            FormatType detectado ou None
        """
        # Verifica se é ZIP
        if not data.startswith(b"PK\x03\x04"):
            return None
        
        # Procura por assinaturas de formato Office no conteúdo do ZIP
        # DOCX: [Content_Types].xml com word/
        # XLSX: [Content_Types].xml com xl/
        # PPTX: [Content_Types].xml com ppt/
        
        # Heurística simples: procura por strings características nos primeiros 4KB
        header = data[:4096].lower()
        
        # Verifica assinaturas Office Open XML
        if b"word/" in header or b"document.xml" in header:
            return FormatType.DOCX
        if b"xl/" in header or b"worksheet" in header:
            return FormatType.XLSX
        if b"ppt/" in header or b"presentation.xml" in header:
            return FormatType.PPTX
        
        # Verifica assinaturas OpenDocument
        if b"mimetype" in header:
            if b"application/vnd.oasis.opendocument.text" in header:
                return FormatType.ODT
            if b"application/vnd.oasis.opendocument.spreadsheet" in header:
                return FormatType.ODS
            if b"application/vnd.oasis.opendocument.presentation" in header:
                return FormatType.ODP
        
        return None
    
    def _detect_format_from_bytes(self, data: bytes) -> FormatType:
        """Detecta formato baseado nos primeiros bytes (magic bytes).
        
        Args:
            data: Primeiros bytes do arquivo
            
        Returns:
            FormatType detectado
        """
        if not data:
            return FormatType.UNKNOWN
        
        # Verifica magic bytes padrão
        for fmt, signatures in MAGIC_BYTES.items():
            for sig in signatures:
                if data.startswith(sig):
                    # Se for ZIP, tenta detectar formato Office
                    if fmt == FormatType.ZIP:
                        office_fmt = self._detect_office_format(data)
                        if office_fmt:
                            return office_fmt
                    return fmt
        
        # Detecção de encoding
        detected_encoding = self._detect_encoding(data)
        
        # Detecção heurística para texto
        try:
            # Usa UTF-8 como default, ou o encoding detectado
            decode_encoding = detected_encoding if detected_encoding else "utf-8"
            text = data[:4096].decode(decode_encoding, errors="ignore")
            
            # Verifica se é texto puro (mais de 90% caracteres imprimíveis)
            if text and len([c for c in text if c.isprintable() or c in '\n\r\t']) / len(text) > 0.9:
                stripped = text.strip()
                if stripped.startswith("<"):
                    if "<html" in text.lower()[:2000]:
                        return FormatType.HTML
                    elif "<?xml" in text.lower()[:200]:
                        return FormatType.XML
                elif stripped.startswith("{") or stripped.startswith("["):
                    try:
                        import json
                        json.loads(stripped[:1024])
                        return FormatType.JSON
                    except json.JSONDecodeError:
                        pass
                
                # CSV heurístico: procura por vírgulas ou ponto-e-vírgula em linhas
                lines = text.split("\n")[:10]
                if len(lines) >= 2:
                    # Verifica consistência de delimitadores
                    delimiters = [",", ";", "\t", "|"]
                    for delim in delimiters:
                        counts = [line.count(delim) for line in lines if line.strip()]
                        if counts and all(c == counts[0] and c > 0 for c in counts):
                            return FormatType.CSV
                
                # Se parece texto mas não é formato específico
                if len(text) > 0:
                    return FormatType.TXT
        except Exception:
            pass
        
        return FormatType.UNKNOWN
    
    def _detect_format_from_content_type(self, content_type: str) -> FormatType:
        """Detecta formato baseado no Content-Type HTTP.
        
        Args:
            content_type: Header Content-Type da resposta
            
        Returns:
            FormatType detectado
        """
        if not content_type:
            return FormatType.UNKNOWN
        
        # Remove charset e outros parâmetros
        main_type = content_type.split(";")[0].strip().lower()
        
        return MIME_TYPE_MAP.get(main_type, FormatType.UNKNOWN)
    
    def _validate_format(
        self, 
        detected_format: FormatType, 
        content_type: str,
        first_bytes: bytes
    ) -> None:
        """Valida se o formato é permitido.
        
        Args:
            detected_format: FormatType detectado
            content_type: Content-Type HTTP
            first_bytes: Primeiros bytes do conteúdo
            
        Raises:
            FetchFormatError: Se o formato não for permitido
        """
        if self.config.allowed_formats is None:
            return
        
        if detected_format not in self.config.allowed_formats:
            raise FetchFormatError(
                f"Format '{detected_format}' not allowed. "
                f"Allowed: {[f.value for f in self.config.allowed_formats]}. "
                f"Content-Type: {content_type}",
                url="",
            )
    
    def _classify_error(self, error: Exception, url: str) -> FetchError:
        """Classifica um erro como retryable ou permanente.
        
        Args:
            error: Exceção ocorrida
            url: URL que causou o erro
            
        Returns:
            FetchError classificado
        """
        if isinstance(error, httpx.TimeoutException):
            return FetchTimeoutError(f"Timeout after {self.config.timeout}s", url)
        
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status >= 500:
                return FetchRetryableError(f"Server error {status}", url, status)
            elif status == 429:
                return FetchRetryableError(f"Rate limited (429)", url, status)
            else:
                return FetchPermanentError(f"Client error {status}", url, status)
        
        if isinstance(error, (httpx.ConnectError, httpx.NetworkError)):
            return FetchRetryableError(f"Network error: {error}", url)
        
        if isinstance(error, FetchError):
            return error
        
        return FetchRetryableError(f"Unexpected error: {error}", url)
    
    async def _fetch_with_retry(
        self, 
        url: str, 
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Executa fetch com retry usando tenacity.
        
        Args:
            url: URL a ser buscada
            method: Método HTTP
            headers: Headers adicionais
            
        Returns:
            Resposta HTTP
            
        Raises:
            FetchError: Em caso de erro
        """
        @retry(
            retry=retry_if_exception_type(FetchRetryableError),
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _do_fetch() -> httpx.Response:
            client = await self._get_client()
            request_headers = headers or {}
            
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                )
                
                # Verifica status code
                if response.status_code >= 400:
                    response.raise_for_status()
                
                return response
                
            except httpx.HTTPStatusError as e:
                classified = self._classify_error(e, url)
                raise classified from e
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                classified = self._classify_error(e, url)
                raise classified from e
            except Exception as e:
                classified = self._classify_error(e, url)
                raise classified from e
        
        try:
            return await _do_fetch()
        except FetchRetryableError as e:
            logger.error(f"Fetch failed after {self.config.max_retries} retries: {url}")
            raise FetchError(f"Max retries exceeded: {e}", url, e.status_code) from e
        except FetchPermanentError as e:
            logger.error(f"Permanent fetch error: {url} - {e}")
            raise FetchError(f"Permanent error: {e}", url, e.status_code) from e
    
    async def _stream_to_temp_file(
        self, 
        response: httpx.Response, 
        url: str,
        content_type: str,
        method: str,
        response_headers: Dict[str, str],
        start_time: float,
    ) -> FetchedContent:
        """Stream large content to temporary file.
        
        Args:
            response: HTTP response with streaming content
            url: Source URL
            content_type: Content-Type header
            method: HTTP method used
            response_headers: All response headers
            start_time: Start time for duration calculation
            
        Returns:
            FetchedContent with path to temp file
            
        Raises:
            FetchSizeError: If content exceeds max size
        """
        temp_path: Optional[str] = None
        
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                temp_path = tmp.name
                total_size = 0
                first_chunk: Optional[bytes] = None
                hasher = hashlib.sha256()
                
                async for chunk in response.aiter_bytes(chunk_size=self.config.chunk_size):
                    if first_chunk is None:
                        first_chunk = chunk
                    
                    total_size += len(chunk)
                    
                    # Check size limit
                    if total_size > self.config.max_size_bytes:
                        tmp.close()
                        os.unlink(temp_path)
                        raise FetchSizeError(
                            f"Downloaded size {total_size} exceeds max {self.config.max_size_bytes}",
                            url,
                        )
                    
                    tmp.write(chunk)
                    hasher.update(chunk)
            
            # Detect format from first chunk
            detected_format = self._detect_format_from_bytes(first_chunk or b"")
            if detected_format == FormatType.UNKNOWN:
                detected_format = self._detect_format_from_content_type(content_type)
            
            # Validate format
            if self.config.validate_magic_bytes:
                self._validate_format(detected_format, content_type, first_chunk or b"")
            
            # Calculate hash and duration
            content_hash = hasher.hexdigest()
            fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
            
            # Create metadata
            metadata = FetchMetadata(
                url=url,
                method=method,
                status_code=response.status_code,
                content_type=content_type,
                content_length=total_size,
                encoding=response.encoding,
                headers=response_headers,
                fetch_duration_ms=fetch_duration_ms,
            )
            
            logger.info(
                f"Fetched (streamed) {url}: {total_size} bytes, "
                f"format={detected_format.value}, "
                f"hash={content_hash[:16]}..., "
                f"duration={fetch_duration_ms}ms, "
                f"temp_file={temp_path}"
            )
            
            return FetchedContent(
                url=url,
                content=None,  # Not in memory
                content_path=temp_path,
                is_streamed=True,
                size_bytes=total_size,
                metadata=metadata,
                fingerprint=content_hash,
            )
            
        except Exception:
            # Cleanup on error
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise
    
    async def _stream_to_memory(
        self, 
        response: httpx.Response,
        url: str,
        content_type: str,
        method: str,
        response_headers: Dict[str, str],
        start_time: float,
    ) -> FetchedContent:
        """Stream small content to memory (original behavior).
        
        Args:
            response: HTTP response with streaming content
            url: Source URL
            content_type: Content-Type header
            method: HTTP method used
            response_headers: All response headers
            start_time: Start time for duration calculation
            
        Returns:
            FetchedContent with content in memory
            
        Raises:
            FetchSizeError: If content exceeds max size
        """
        chunks: list[bytes] = []
        total_size = 0
        first_chunk: Optional[bytes] = None
        hasher = hashlib.sha256()
        
        async for chunk in response.aiter_bytes(chunk_size=self.config.chunk_size):
            if first_chunk is None:
                first_chunk = chunk
            
            total_size += len(chunk)
            
            # Check size limit during streaming
            if total_size > self.config.max_size_bytes:
                raise FetchSizeError(
                    f"Downloaded size {total_size} exceeds max {self.config.max_size_bytes}",
                    url,
                )
            
            chunks.append(chunk)
            hasher.update(chunk)
        
        # Concatenate chunks
        raw_bytes = b"".join(chunks) if len(chunks) > 1 else (chunks[0] if chunks else b"")
        
        # Detect format
        detected_format = self._detect_format_from_bytes(first_chunk or b"")
        if detected_format == FormatType.UNKNOWN:
            detected_format = self._detect_format_from_content_type(content_type)
        
        # Validate format
        if self.config.validate_magic_bytes:
            self._validate_format(detected_format, content_type, first_chunk or b"")
        
        # Calculate hash and duration
        content_hash = hasher.hexdigest()
        fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
        
        # Create metadata
        metadata = FetchMetadata(
            url=url,
            method=method,
            status_code=response.status_code,
            content_type=content_type,
            content_length=total_size,
            encoding=response.encoding,
            headers=response_headers,
            fetch_duration_ms=fetch_duration_ms,
        )
        
        logger.info(
            f"Fetched (memory) {url}: {total_size} bytes, "
            f"format={detected_format.value}, "
            f"hash={content_hash[:16]}..., "
            f"duration={fetch_duration_ms}ms"
        )
        
        return FetchedContent(
            url=url,
            content=raw_bytes,
            content_path=None,
            is_streamed=False,
            size_bytes=total_size,
            metadata=metadata,
            fingerprint=content_hash,
        )
    
    async def fetch(
        self, 
        url: str, 
        source_id: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
    ) -> FetchedContent:
        """Faz download de conteúdo de uma URL.
        
        Executa o download com streaming inteligente:
        - Arquivos pequenos (< stream_threshold): carregados em memória
        - Arquivos grandes (>= stream_threshold): stream para disco
        
        Validação de magic bytes, cálculo de hash e limites de segurança
        são aplicados independentemente do modo.
        
        Security:
            - Validação SSRF antes do request
            - Circuit breaker por domínio
            - Limite de tamanho para prevenir DoS
        
        Args:
            url: URL do conteúdo
            source_id: ID da fonte (para rastreamento)
            method: Método HTTP (padrão: GET)
            headers: Headers HTTP adicionais
            
        Returns:
            FetchedContent com o conteúdo e metadados
            
        Raises:
            FetchError: Em caso de erro no download
            FetchSizeError: Se o arquivo exceder o tamanho máximo
            FetchFormatError: Se o formato não for permitido
            FetchSSRFError: Se URL for bloqueada por segurança
            CircuitBreakerOpenError: Se circuit breaker estiver aberto
            
        Example:
            >>> fetcher = ContentFetcher()
            >>> content = await fetcher.fetch(
            ...     "https://example.com/data.csv",
            ...     source_id="tcu_acordaos"
            ... )
            >>> print(f"Downloaded {content.size_bytes} bytes")
            >>> if content.is_streamed:
            ...     data = content.get_content()  # Read from file
            ...     content.cleanup()  # Remove temp file
        """
        start_time = time.monotonic()
        logger.info(f"Fetching {url} for source {source_id}")
        
        try:
            # 1. Validação SSRF
            self._ssrf_protector.validate_url(url)
            
            # 2. Verifica circuit breaker
            cb = self._get_circuit_breaker(url)
            if not cb.can_execute():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN for domain",
                    url
                )
            
            # 3. Executa o fetch com retry
            response = await self._fetch_with_retry(url, method, headers)
            
            # 4. Registra sucesso no circuit breaker
            cb.record_success()
            
            # 5. Obtém headers
            response_headers = dict(response.headers)
            content_type = response_headers.get("content-type", "application/octet-stream")
            
            # 6. Verifica Content-Length se disponível
            content_length = response_headers.get("content-length")
            if content_length:
                size_hint = int(content_length)
                if size_hint > self.config.max_size_bytes:
                    raise FetchSizeError(
                        f"Content-Length {size_hint} exceeds max {self.config.max_size_bytes}",
                        url,
                    )
                
                # Decide streaming strategy based on content length
                if size_hint >= self.config.stream_threshold:
                    return await self._stream_to_temp_file(
                        response, url, content_type, method, response_headers, start_time
                    )
                else:
                    return await self._stream_to_memory(
                        response, url, content_type, method, response_headers, start_time
                    )
            else:
                # No content-length, usa streaming em memória
                # Mas verifica threshold durante o streaming
                return await self._stream_to_memory(
                    response, url, content_type, method, response_headers, start_time
                )
            
        except FetchSizeError:
            raise
        except FetchSSRFError:
            raise
        except CircuitBreakerOpenError:
            raise
        except FetchRetryableError as e:
            # Registra falha no circuit breaker
            cb = self._get_circuit_breaker(url)
            cb.record_failure()
            raise FetchError(f"Max retries exceeded: {e}", url, e.status_code) from e
        except FetchError:
            raise
        except Exception as e:
            # Registra falha no circuit breaker para erros não-tratados
            try:
                cb = self._get_circuit_breaker(url)
                cb.record_failure()
            except Exception:
                pass
            logger.exception(f"Unexpected error fetching {url}")
            raise FetchError(f"Unexpected error: {e}", url) from e
    
    async def fetch_head(self, url: str, headers: Optional[Dict[str, str]] = None) -> FetchMetadata:
        """Executa HEAD request para obter metadados sem baixar o conteúdo.
        
        Args:
            url: URL a ser verificada
            headers: Headers adicionais
            
        Returns:
            FetchMetadata com informações do recurso
            
        Raises:
            FetchError: Em caso de erro
            FetchSSRFError: Se URL for bloqueada por segurança
        """
        start_time = time.monotonic()
        
        try:
            # Validação SSRF
            self._ssrf_protector.validate_url(url)
            
            client = await self._get_client()
            response = await client.head(url, headers=headers)
            response.raise_for_status()
            
            fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
            
            return FetchMetadata(
                url=url,
                method="HEAD",
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                content_length=int(response.headers.get("content-length", 0)) if "content-length" in response.headers else None,
                encoding=None,
                headers=dict(response.headers),
                fetch_duration_ms=fetch_duration_ms,
            )
            
        except httpx.HTTPStatusError as e:
            raise FetchError(f"HTTP error: {e}", url, e.response.status_code) from e
        except FetchSSRFError:
            raise
        except Exception as e:
            raise FetchError(f"HEAD request failed: {e}", url) from e
    
    def update_config(self, **kwargs) -> "ContentFetcher":
        """Atualiza configuração do fetcher (chainable).
        
        Args:
            **kwargs: Atributos a serem atualizados
            
        Returns:
            Self para chaining
            
        Raises:
            ValueError: Se chave for inválida
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                raise ValueError(f"Invalid config key: {key}")
        
        # Re-valida configuração
        self.config.validate()
        
        # Recria SSRF protector com nova config
        if 'ssrf_config' in kwargs:
            self._ssrf_protector = SSRFProtector(self.config.ssrf_config)
        
        return self
    
    def get_circuit_breaker_stats(self) -> Dict[str, Dict[str, Any]]:
        """Retorna estatísticas de circuit breakers.
        
        Returns:
            Dicionário com estatísticas por domínio
        """
        return {
            domain: cb.get_stats()
            for domain, cb in self._circuit_breakers.items()
        }
    
    def reset_circuit_breaker(self, domain: Optional[str] = None) -> None:
        """Reseta circuit breaker(s).
        
        Args:
            domain: Domínio específico ou None para resetar todos
        """
        if domain:
            if domain in self._circuit_breakers:
                del self._circuit_breakers[domain]
        else:
            self._circuit_breakers.clear()
