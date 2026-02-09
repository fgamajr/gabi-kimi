"""Parser de conteúdo para o pipeline de ingestão.

Fornece estrutura extensível para parsing de diferentes formatos de conteúdo.
Baseado em CONTRACTS.md §2.4.

Security Features:
    - Size limits (MAX_PARSE_SIZE = 100MB)
    - Page limits for PDFs (default 1000 pages)
    - Password-protected PDF handling
    - HTML entity expansion protection (XSS, billion laughs)
    - CSV row limits and smart delimiter detection
    - Quarantine for suspicious files
"""

import csv
import hashlib
import io
import logging
import os
import re
import tempfile
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from gabi.pipeline.contracts import FetchedContent, ParseResult, ParsedDocument
from gabi.pipeline.transforms import apply_transform

# Configure logger
logger = logging.getLogger(__name__)

# =============================================================================
# Security Constants
# =============================================================================

MAX_PARSE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_CSV_ROWS = 1_000_000  # 1 million rows
# Max CSV field size. 10KB is too restrictive for legal corpora with long text columns.
MAX_CSV_ROW_LENGTH = 5 * 1024 * 1024  # 5MB per field
MAX_HTML_ENTITY_EXPANSION = 10_000  # Prevent billion laughs attack
MAX_HTML_SIZE = 50 * 1024 * 1024  # 50MB for HTML (before parsing)
DEFAULT_PDF_MAX_PAGES = 1000  # Default page limit for PDFs
PDF_MAX_PAGES_HARD = 10_000  # Absolute maximum pages
MAX_PDF_TEXT_SIZE_PER_PAGE = 10 * 1024 * 1024  # 10MB text per page

# Quarantine configuration (defaults, can be overridden via function)
_DEFAULT_QUARANTINE_DIR = "/tmp/gabi_quarantine"
_DEFAULT_QUARANTINE_ENABLED = True


def _get_quarantine_config() -> Tuple[bool, str]:
    """Get quarantine configuration from environment variables.
    
    This function reads the configuration fresh each time, allowing
    tests to modify environment variables without module reload.
    
    Returns:
        Tuple of (enabled, directory)
    """
    enabled = os.environ.get("GABI_QUARANTINE_ENABLED", "true").lower() in ("true", "1", "yes")
    directory = os.environ.get("GABI_QUARANTINE_DIR", _DEFAULT_QUARANTINE_DIR)
    return enabled, directory


# Keep module-level constants for backward compatibility
QUARANTINE_DIR = os.environ.get("GABI_QUARANTINE_DIR", "/tmp/gabi_quarantine")
QUARANTINE_ENABLED = os.environ.get("GABI_QUARANTINE_ENABLED", "true").lower() in ("true", "1", "yes")


# =============================================================================
# Base Parser
# =============================================================================

class BaseParser(ABC):
    """Classe base abstrata para todos os parsers.
    
    Define a interface que todos os parsers devem implementar.
    """
    
    @abstractmethod
    async def parse(self, content: FetchedContent, config: Dict[str, Any]) -> ParseResult:
        """Parseia o conteúdo buscado em documentos estruturados.
        
        Args:
            content: Conteúdo buscado na fase de fetch
            config: Configuração específica do parser
            
        Returns:
            ParseResult com documentos extraídos e metadados
        """
        ...
    
    def _generate_document_id(self, source_id: str, content: str) -> str:
        """Gera um ID único para o documento.
        
        Args:
            source_id: ID da fonte
            content: Conteúdo do documento
            
        Returns:
            ID único do documento
        """
        content_hash = hashlib.sha256(f"{source_id}:{content}".encode()).hexdigest()[:16]
        return f"doc_{source_id}_{content_hash}"
    
    def _generate_content_hash(self, content: str) -> str:
        """Gera um hash do conteúdo.
        
        Args:
            content: Conteúdo do documento
            
        Returns:
            Hash SHA256 do conteúdo
        """
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _create_preview(self, content: str, max_length: int = 500) -> str:
        """Cria um preview do conteúdo.
        
        Args:
            content: Conteúdo completo
            max_length: Tamanho máximo do preview
            
        Returns:
            Preview truncado do conteúdo
        """
        if len(content) <= max_length:
            return content
        return content[:max_length] + "..."

    def _check_size_limit(self, content: FetchedContent, max_size: int = MAX_PARSE_SIZE) -> Tuple[bool, int]:
        """Verifica se o conteúdo excede o limite de tamanho.
        
        Args:
            content: Conteúdo a verificar
            max_size: Tamanho máximo permitido em bytes
            
        Returns:
            Tuple (within_limit, size_bytes)
        """
        size = content.size_bytes
        if size == 0 and content.content is not None:
            size = len(content.content)
        return size <= max_size, size


# =============================================================================
# Security Utilities
# =============================================================================

def _detect_csv_dialect(sample: str) -> Tuple[str, str]:
    """Detecta o delimitador e quotechar do CSV de forma inteligente.
    
    Args:
        sample: Amostra do conteúdo CSV
        
    Returns:
        Tuple (delimiter, quotechar)
    """
    # Common delimiters to test
    delimiters = [',', ';', '\t', '|', ':']
    
    # Count occurrences in each line
    lines = sample.split('\n')[:10]  # Sample first 10 lines
    if not lines:
        return ',', '"'
    
    best_delimiter = ','
    max_consistency = 0
    
    for delimiter in delimiters:
        counts = [line.count(delimiter) for line in lines if line.strip()]
        if counts and all(c == counts[0] for c in counts) and counts[0] > 0:
            # All lines have same count - strong candidate
            if counts[0] > max_consistency:
                max_consistency = counts[0]
                best_delimiter = delimiter
        elif counts and sum(counts) > max_consistency:
            # Fallback: use most frequent
            max_consistency = sum(counts)
            best_delimiter = delimiter
    
    # Detect quotechar
    quotechars = ['"', "'"]
    best_quotechar = '"'
    max_quotes = 0
    
    for quotechar in quotechars:
        count = sample.count(quotechar)
        if count > max_quotes:
            max_quotes = count
            best_quotechar = quotechar
    
    return best_delimiter, best_quotechar


def _sanitize_html_content(content: str, allowed_tags: Optional[List[str]] = None) -> str:
    """Sanitiza conteúdo HTML removendo scripts e event handlers.
    
    Args:
        content: Conteúdo HTML
        allowed_tags: Lista de tags permitidas (None = todas exceto perigosas)
        
    Returns:
        HTML sanitizado
    """
    # Remove script and style blocks first (regex-based pre-processing)
    # This is a first pass - BeautifulSoup will do the main cleaning
    dangerous_patterns = [
        (r'<script[^>]*>.*?</script>', '', re.DOTALL | re.IGNORECASE),
        (r'<style[^>]*>.*?</style>', '', re.DOTALL | re.IGNORECASE),
        (r'javascript:', '', re.IGNORECASE),
        (r'on\w+\s*=\s*["\'][^"\']*["\']', '', re.IGNORECASE),
        (r'on\w+\s*=\s*[^\s>]+', '', re.IGNORECASE),
    ]
    
    sanitized = content
    for pattern, replacement, flags in dangerous_patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=flags)
    
    return sanitized


def _check_html_entity_expansion(content: str, max_expansion: int = MAX_HTML_ENTITY_EXPANSION) -> Tuple[bool, int]:
    """Verifica se há expansão excessiva de entidades (billion laughs protection).
    
    Args:
        content: Conteúdo HTML/XML
        max_expansion: Máximo de entidades permitidas
        
    Returns:
        Tuple (is_safe, entity_count)
    """
    # Count entity references
    entity_pattern = re.compile(r'&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);')
    entities = entity_pattern.findall(content)
    
    # Check for nested entity definitions (DOCTYPE)
    doctype_pattern = re.compile(r'<!ENTITY\s+\w+\s+"([^"]*)"\s*>', re.IGNORECASE)
    entity_defs = doctype_pattern.findall(content)
    
    # Calculate expansion factor
    total_entity_count = len(entities)
    for def_content in entity_defs:
        total_entity_count += def_content.count('&')
    
    is_safe = total_entity_count <= max_expansion
    return is_safe, total_entity_count


def _quarantine_file(content: FetchedContent, reason: str, error_details: Dict[str, Any]) -> str:
    """Move arquivo suspeito para quarentena.
    
    Args:
        content: Conteúdo a ser quarentinado
        reason: Motivo da quarentena
        error_details: Detalhes do erro
        
    Returns:
        Path do arquivo em quarentena
    """
    quarantine_enabled, quarantine_dir = _get_quarantine_config()
    
    if not quarantine_enabled:
        return ""
    
    try:
        # Create quarantine directory
        os.makedirs(quarantine_dir, exist_ok=True)
        
        # Generate quarantine filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        content_hash = hashlib.sha256(content.url.encode()).hexdigest()[:12]
        filename = f"{timestamp}_{content_hash}_{os.path.basename(content.url) or 'unknown'}"
        quarantine_path = os.path.join(quarantine_dir, filename)
        
        # Save content
        raw_content = content.get_content()
        with open(quarantine_path, 'wb') as f:
            f.write(raw_content)
        
        # Save metadata
        meta_path = quarantine_path + ".meta"
        import json
        with open(meta_path, 'w') as f:
            json.dump({
                "url": content.url,
                "reason": reason,
                "timestamp": timestamp,
                "error_details": error_details,
            }, f, indent=2, default=str)
        
        logger.warning(f"File quarantined: {quarantine_path}, reason: {reason}")
        return quarantine_path
        
    except Exception as e:
        logger.error(f"Failed to quarantine file: {e}")
        return ""


# =============================================================================
# Parse Error Metrics
# =============================================================================

class ParseErrorMetrics:
    """Métricas de erro de parsing para monitoramento.
    
    Esta classe registra estatísticas de erros para análise.
    """
    
    def __init__(self):
        """Inicializa métricas vazias."""
        self.errors_by_type: Dict[str, int] = {}
        self.errors_by_format: Dict[str, int] = {}
        self.quarantine_count = 0
        self.total_parsed = 0
        self.total_failed = 0
    
    def record_error(self, error_type: str, format_type: str, quarantined: bool = False) -> None:
        """Registra um erro de parsing.
        
        Args:
            error_type: Tipo do erro (ex: 'SizeLimitExceeded', 'PDFPasswordProtected')
            format_type: Formato do arquivo (ex: 'pdf', 'html', 'csv')
            quarantined: Se o arquivo foi quarentinado
        """
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        self.errors_by_format[format_type] = self.errors_by_format.get(format_type, 0) + 1
        self.total_failed += 1
        if quarantined:
            self.quarantine_count += 1
    
    def record_success(self, format_type: str) -> None:
        """Registra um parsing bem-sucedido.
        
        Args:
            format_type: Formato do arquivo
        """
        self.total_parsed += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de erros.
        
        Returns:
            Dicionário com estatísticas
        """
        total = self.total_parsed + self.total_failed
        failure_rate = self.total_failed / total if total > 0 else 0.0
        
        return {
            "total_parsed": self.total_parsed,
            "total_failed": self.total_failed,
            "failure_rate": failure_rate,
            "quarantine_count": self.quarantine_count,
            "errors_by_type": dict(self.errors_by_type),
            "errors_by_format": dict(self.errors_by_format),
        }


# Global metrics instance
_parse_error_metrics = ParseErrorMetrics()


def get_parse_error_metrics() -> ParseErrorMetrics:
    """Retorna a instância global de métricas de erro.
    
    Returns:
        Instância de ParseErrorMetrics
    """
    return _parse_error_metrics


# =============================================================================
# Parser Registry
# =============================================================================

class ParserRegistry:
    """Registro extensível de parsers por formato.
    
    Permite registrar e recuperar parsers dinamicamente,
    facilitando a extensão com novos formatos.
    """
    
    def __init__(self):
        """Inicializa o registro vazio."""
        self._parsers: Dict[str, BaseParser] = {}
    
    def register(self, format: str, parser: BaseParser) -> None:
        """Registra um parser para um formato.
        
        Args:
            format: Nome do formato (ex: 'csv', 'html', 'json')
            parser: Instância do parser
        """
        self._parsers[format.lower()] = parser
    
    def get_parser(self, format: str) -> Optional[BaseParser]:
        """Retorna o parser para um formato.
        
        Args:
            format: Nome do formato
            
        Returns:
            Parser registrado ou None se não existir
        """
        return self._parsers.get(format.lower())
    
    def unregister(self, format: str) -> bool:
        """Remove um parser do registro.
        
        Args:
            format: Nome do formato
            
        Returns:
            True se removeu, False se não existia
        """
        format_lower = format.lower()
        if format_lower in self._parsers:
            del self._parsers[format_lower]
            return True
        return False
    
    def list_formats(self) -> List[str]:
        """Lista todos os formatos registrados.
        
        Returns:
            Lista de nomes de formatos
        """
        return list(self._parsers.keys())
    
    def has_parser(self, format: str) -> bool:
        """Verifica se existe parser para um formato.
        
        Args:
            format: Nome do formato
            
        Returns:
            True se existe parser
        """
        return format.lower() in self._parsers


# =============================================================================
# Content Parser
# =============================================================================

class ContentParser:
    """Parser de alto nível que delega para o parser correto."""

    def __init__(self, registry: Optional[ParserRegistry] = None) -> None:
        self._registry = registry or get_registry()

    async def parse(self, content: FetchedContent, config: Dict[str, Any]) -> ParseResult:
        """Seleciona o parser pelo formato e executa o parse."""
        fmt = config.get("input_format") or config.get("format") or config.get("parser")
        if not fmt:
            raise ValueError("input_format é obrigatório para parsing")
        parser = self._registry.get_parser(fmt)
        if not parser:
            raise ValueError(f"Parser não registrado para formato: {fmt}")
        return await parser.parse(content, config)


# =============================================================================
# CSV Parser
# =============================================================================

class CSVParser(BaseParser):
    """Parser para arquivos CSV.
    
    Suporta delimitadores configuráveis e converte cada linha
    em um documento estruturado.
    
    Security Features:
        - Row limits (MAX_CSV_ROWS = 1M)
        - UTF-8 BOM handling
        - Smart delimiter detection
        - Row length limits
    """
    
    DEFAULT_DELIMITER = ","
    DEFAULT_QUOTECHAR = '"'
    DEFAULT_ENCODING = "utf-8"
    
    def _apply_mapping_transforms(
        self, 
        row: Dict[str, str], 
        mapping: Dict[str, Any]
    ) -> Dict[str, str]:
        """Aplica transforms aos valores da row baseado no mapping.
        
        Args:
            row: Dicionário com valores da linha do CSV
            mapping: Configuração de mapeamento com transforms
                Ex: {"title": {"from": "TITULO", "transform": "strip_quotes"}}
                
        Returns:
            Nova row com valores transformados
        """
        processed = dict(row)
        
        for field_name, field_config in mapping.items():
            if isinstance(field_config, dict):
                source_col = field_config.get("from")
                transform_name = field_config.get("transform")
            else:
                # Caso simples: mapping[field] = "source_column"
                source_col = field_config
                transform_name = None
            
            if source_col and source_col in row:
                value = row[source_col]
                
                # Aplica transform se especificado
                if transform_name:
                    try:
                        value = apply_transform(transform_name, value)
                    except ValueError:
                        # Transform não encontrado, mantém valor original
                        pass
                
                # Adiciona ao processed com o nome do campo destino
                processed[field_name] = value
        
        return processed
    
    def _decode_with_bom_handling(self, raw_content: bytes, encoding: str) -> Tuple[str, str]:
        """Decodifica conteúdo com tratamento de UTF-8 BOM.
        
        Args:
            raw_content: Bytes do conteúdo
            encoding: Encoding especificado
            
        Returns:
            Tuple (text_content, detected_encoding)
        """
        # Check for UTF-8 BOM
        if raw_content.startswith(b'\xef\xbb\xbf'):
            text_content = raw_content[3:].decode('utf-8')
            return text_content, 'utf-8-sig'
        
        # Check for UTF-16 BOMs
        if raw_content.startswith(b'\xff\xfe'):
            text_content = raw_content.decode('utf-16-le')
            return text_content, 'utf-16-le'
        if raw_content.startswith(b'\xfe\xff'):
            text_content = raw_content.decode('utf-16-be')
            return text_content, 'utf-16-be'
        
        # Try specified encoding
        try:
            text_content = raw_content.decode(encoding)
            return text_content, encoding
        except UnicodeDecodeError:
            # Fallback to utf-8 with error handling
            text_content = raw_content.decode('utf-8', errors='replace')
            return text_content, 'utf-8-replace'
    
    async def parse(self, content: FetchedContent, config: Dict[str, Any]) -> ParseResult:
        """Parseia conteúdo CSV em documentos.
        
        Cada linha do CSV vira um documento separado com os campos
        mapeados para texto e metadados.
        
        Security:
            - Respects MAX_CSV_ROWS limit
            - Respects MAX_PARSE_SIZE limit
            - Handles UTF-8 BOM properly
            - Smart delimiter detection
        
        Args:
            content: Conteúdo CSV buscado
            config: Configuração com:
                - delimiter: Delimitador de campos (padrão: auto-detect)
                - quotechar: Caractere de quote (padrão: auto-detect)
                - encoding: Encoding do arquivo (padrão: 'utf-8')
                - title_column: Nome da coluna para título
                - content_columns: Lista de colunas para conteúdo
                - source_id: ID da fonte (obrigatório)
                - mapping: Dict com mapeamento de campos e transforms
                    Ex: {"title": {"from": "TITULO", "transform": "strip_quotes"}}
                - max_rows: Máximo de linhas a processar (padrão: MAX_CSV_ROWS)
                
        Returns:
            ParseResult com documentos extraídos
        """
        start_time = datetime.utcnow()
        documents: List[ParsedDocument] = []
        errors: List[Dict[str, Any]] = []
        metrics = get_parse_error_metrics()
        
        max_parse_size = int(config.get("max_parse_size_bytes", MAX_PARSE_SIZE))
        max_parse_size = max(1024 * 1024, min(max_parse_size, 2 * 1024 * 1024 * 1024))

        # Check size limit first
        within_limit, content_size = self._check_size_limit(content, max_parse_size)
        if not within_limit:
            error_type = "SizeLimitExceeded"
            error_details = {
                "error": f"CSV size ({content_size} bytes) exceeds maximum ({max_parse_size} bytes)",
                "error_type": error_type,
                "size_bytes": content_size,
                "max_size_bytes": max_parse_size,
            }
            quarantine_path = _quarantine_file(content, error_type, error_details)
            metrics.record_error(error_type, "csv", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=content_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
        
        # Configurações
        delimiter = config.get("delimiter")
        quotechar = config.get("quotechar")
        encoding = config.get("encoding", self.DEFAULT_ENCODING)
        title_column = config.get("title_column")
        content_columns = config.get("content_columns", [])
        source_id = config.get("source_id", "unknown")
        mapping = config.get("mapping", {})
        max_rows = config.get("max_rows", MAX_CSV_ROWS)
        csv_field_size_limit = config.get("csv_field_size_limit", MAX_CSV_ROW_LENGTH)
        csv_field_size_limit = max(1024, min(int(csv_field_size_limit), max_parse_size))
        
        try:
            # Get content (handles both streamed and in-memory)
            raw_content = content.get_content()
            
            # Decodifica o conteúdo com tratamento de BOM
            text_content, detected_encoding = self._decode_with_bom_handling(raw_content, encoding)
            raw_size = len(raw_content)
            
            # Auto-detect delimiter if not specified
            if delimiter is None or quotechar is None:
                sample = text_content[:4096]  # Sample first 4KB
                detected_delimiter, detected_quotechar = _detect_csv_dialect(sample)
                delimiter = delimiter or detected_delimiter
                quotechar = quotechar or detected_quotechar
            else:
                delimiter = delimiter or self.DEFAULT_DELIMITER
                quotechar = quotechar or self.DEFAULT_QUOTECHAR
            
            # Parseia o CSV com limite de tamanho de linha
            csv.field_size_limit(csv_field_size_limit)
            reader = csv.DictReader(
                io.StringIO(text_content),
                delimiter=delimiter,
                quotechar=quotechar
            )
            
            headers = reader.fieldnames or []
            row_count = 0
            rows_truncated = False
            
            for row in reader:
                row_count += 1
                
                # Check row limit
                if row_count > max_rows:
                    rows_truncated = True
                    errors.append({
                        "row": row_count,
                        "error": f"Row limit exceeded (max: {max_rows})",
                        "error_type": "RowLimitExceeded",
                    })
                    break
                
                try:
                    # Aplica transforms aos valores da row baseado no mapping
                    processed_row = self._apply_mapping_transforms(row, mapping)
                    
                    # Extrai título (usa title_column ou mapping para 'title')
                    title = None
                    if title_column and title_column in processed_row:
                        title = processed_row[title_column].strip() or None
                    elif "title" in mapping:
                        title = processed_row.get("title", "").strip() or None
                    
                    # Constrói conteúdo a partir das colunas especificadas
                    # ou usa todas as colunas se nenhuma especificada
                    if content_columns:
                        content_parts = [
                            f"{col}: {processed_row.get(col, '')}"
                            for col in content_columns
                            if col in processed_row
                        ]
                    else:
                        content_parts = [
                            f"{key}: {value}"
                            for key, value in processed_row.items()
                        ]
                    
                    row_content = "\n".join(content_parts)
                    
                    # Cria documento
                    doc_id = self._generate_document_id(
                        source_id, 
                        f"{content.url}:{row_count}"
                    )
                    
                    document = ParsedDocument(
                        document_id=doc_id,
                        source_id=source_id,
                        title=title or f"Row {row_count}",
                        content=row_content,
                        content_preview=self._create_preview(row_content),
                        content_type="text/csv",
                        content_hash=self._generate_content_hash(row_content),
                        url=content.url,
                        metadata={
                            "row_number": row_count,
                            "csv_headers": headers,
                            "raw_data": dict(processed_row),
                            "delimiter": delimiter,
                            "detected_encoding": detected_encoding,
                            "rows_truncated": rows_truncated,
                        },
                        parsed_at=datetime.utcnow(),
                        parsing_duration_ms=0,
                    )
                    
                    documents.append(document)
                    
                except Exception as e:
                    errors.append({
                        "row": row_count,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    })
            
            # Calcula tamanho total parseado
            parsed_size = sum(len(doc.content) for doc in documents)
            
            # Calcula duração
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            metrics.record_success("csv")
            
            return ParseResult(
                documents=documents,
                errors=errors,
                raw_content_size=raw_size,
                parsed_content_size=parsed_size,
                duration_seconds=duration,
            )
            
        except UnicodeDecodeError as e:
            raw_size = len(content.get_content()) if content.content_path or content.content else 0
            error_details = {
                "error": f"Encoding error: {str(e)}",
                "error_type": "UnicodeDecodeError",
                "encoding": encoding,
            }
            metrics.record_error("UnicodeDecodeError", "csv")
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
            
        except csv.Error as e:
            raw_size = len(content.get_content()) if content.content_path or content.content else 0
            error_details = {
                "error": f"CSV parse error: {str(e)}",
                "error_type": "CSVError",
                "delimiter": delimiter,
            }
            quarantine_path = _quarantine_file(content, "CSVError", error_details)
            metrics.record_error("CSVError", "csv", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
            
        except Exception as e:
            raw_size = len(content.get_content()) if content.content_path or content.content else 0
            error_details = {
                "error": f"Unexpected error: {str(e)}",
                "error_type": type(e).__name__,
            }
            quarantine_path = _quarantine_file(content, type(e).__name__, error_details)
            metrics.record_error(type(e).__name__, "csv", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )


# =============================================================================
# Registry Instance
# =============================================================================

# Instância global do registro
_parser_registry = ParserRegistry()


def get_registry() -> ParserRegistry:
    """Retorna a instância global do registro.
    
    Returns:
        Instância do ParserRegistry
    """
    return _parser_registry


def register_parser(format: str, parser: BaseParser) -> None:
    """Registra um parser no registro global.
    
    Args:
        format: Nome do formato
        parser: Instância do parser
    """
    _parser_registry.register(format, parser)


def get_parser(format: str) -> Optional[BaseParser]:
    """Retorna parser do registro global.
    
    Args:
        format: Nome do formato
        
    Returns:
        Parser ou None
    """
    return _parser_registry.get_parser(format)


class ContentParser:
    """Wrapper para acesso ao registro global de parsers."""

    def __init__(self, registry: Optional[ParserRegistry] = None) -> None:
        self._registry = registry or get_registry()

    async def parse(self, content: FetchedContent, config: Dict[str, Any]) -> ParseResult:
        format_type = config.get("input_format") or config.get("format")
        if not format_type:
            raise ValueError("input_format é obrigatório para parsing")

        parser = self._registry.get_parser(format_type)
        if parser is None:
            raise ValueError(f"Parser não encontrado para formato: {format_type}")

        return await parser.parse(content, config)



# =============================================================================
# HTML Parser
# =============================================================================

class HTMLParser(BaseParser):
    """Parser para arquivos HTML.
    
    Usa BeautifulSoup4 para extrair texto relevante de documentos HTML,
    removendo scripts, styles e outros elementos não relevantes.
    Suporta configuração de seletores CSS opcional.
    
    Security Features:
        - Entity expansion protection (billion laughs)
        - XSS sanitization
        - Size limits before parsing
        - Configurable HTML sanitization
    """
    
    DEFAULT_ENCODING = "utf-8"
    
    async def parse(self, content: FetchedContent, config: Dict[str, Any]) -> ParseResult:
        """Parseia conteúdo HTML em documentos.
        
        Extrai texto relevante do HTML usando BeautifulSoup, removendo
        scripts, styles e elementos de navegação.
        
        Security:
            - Respects MAX_HTML_SIZE limit before parsing
            - Checks for entity expansion attacks
            - Sanitizes HTML to prevent XSS
            - Removes dangerous tags and attributes
        
        Args:
            content: Conteúdo HTML buscado
            config: Configuração com:
                - encoding: Encoding do arquivo (padrão: 'utf-8')
                - css_selector: Seletor CSS opcional para extrair seção específica
                - remove_tags: Lista de tags para remover (padrão: ['script', 'style', 'nav'])
                - source_id: ID da fonte (obrigatório)
                - title_selector: Seletor CSS para extrair título (padrão: 'title')
                - sanitize: Se deve sanitizar HTML (padrão: True)
                - allowed_tags: Lista de tags permitidas (None = todas exceto perigosas)
                
        Returns:
            ParseResult com documento extraído
        """
        from bs4 import BeautifulSoup
        
        start_time = datetime.utcnow()
        documents: List[ParsedDocument] = []
        errors: List[Dict[str, Any]] = []
        metrics = get_parse_error_metrics()
        
        # Check size limit first (before parsing)
        within_limit, content_size = self._check_size_limit(content, MAX_HTML_SIZE)
        if not within_limit:
            error_type = "SizeLimitExceeded"
            error_details = {
                "error": f"HTML size ({content_size} bytes) exceeds maximum ({MAX_HTML_SIZE} bytes)",
                "error_type": error_type,
                "size_bytes": content_size,
                "max_size_bytes": MAX_HTML_SIZE,
            }
            quarantine_path = _quarantine_file(content, error_type, error_details)
            metrics.record_error(error_type, "html", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=content_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
        
        # Configurações
        encoding = config.get("encoding", self.DEFAULT_ENCODING)
        css_selector = config.get("css_selector")
        remove_tags = config.get("remove_tags", ["script", "style", "nav", "iframe", "noscript", "object", "embed", "form"])
        source_id = config.get("source_id", "unknown")
        title_selector = config.get("title_selector", "title")
        sanitize = config.get("sanitize", True)
        allowed_tags = config.get("allowed_tags")
        
        try:
            # Get content (handles both streamed and in-memory)
            raw_content = content.get_content()
            
            # Decodifica o conteúdo
            text_content = raw_content.decode(encoding)
            raw_size = len(raw_content)
            
            # Check for entity expansion attacks
            is_safe, entity_count = _check_html_entity_expansion(text_content, MAX_HTML_ENTITY_EXPANSION)
            if not is_safe:
                error_type = "EntityExpansionAttack"
                error_details = {
                    "error": f"Possible entity expansion attack detected ({entity_count} entities)",
                    "error_type": error_type,
                    "entity_count": entity_count,
                    "max_allowed": MAX_HTML_ENTITY_EXPANSION,
                }
                quarantine_path = _quarantine_file(content, error_type, error_details)
                metrics.record_error(error_type, "html", bool(quarantine_path))
                
                return ParseResult(
                    documents=[],
                    errors=[error_details],
                    raw_content_size=raw_size,
                    parsed_content_size=0,
                    duration_seconds=0.0,
                )
            
            # Sanitize HTML if requested
            if sanitize:
                text_content = _sanitize_html_content(text_content, allowed_tags)
            
            # Parseia o HTML
            soup = BeautifulSoup(text_content, 'html.parser')
            
            # Remove tags indesejadas (security + cleanup)
            for tag_name in remove_tags:
                for tag in soup.find_all(tag_name):
                    tag.decompose()
            
            # Remove event handlers and javascript: URLs from all tags
            for tag in soup.find_all(True):
                # Remove event handlers
                attrs_to_remove = [
                    attr for attr in tag.attrs 
                    if attr.startswith('on') or 
                    (isinstance(tag.attrs[attr], str) and tag.attrs[attr].startswith('javascript:'))
                ]
                for attr in attrs_to_remove:
                    del tag.attrs[attr]
            
            # Extrai título
            title = None
            title_tag = soup.select_one(title_selector)
            if title_tag:
                title = title_tag.get_text(strip=True) or None
            
            # Seleciona conteúdo com CSS selector ou usa o body
            if css_selector:
                selected = soup.select_one(css_selector)
                if selected:
                    main_content = selected.get_text(separator='\n', strip=True)
                else:
                    main_content = ""
            else:
                # Tenta encontrar conteúdo principal
                main = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
                if main:
                    main_content = main.get_text(separator='\n', strip=True)
                else:
                    # Fallback para body
                    body = soup.find('body')
                    if body:
                        main_content = body.get_text(separator='\n', strip=True)
                    else:
                        main_content = soup.get_text(separator='\n', strip=True)
            
            # Limpa linhas vazias excessivas
            lines = [line for line in main_content.split('\n') if line.strip()]
            cleaned_content = '\n'.join(lines)
            
            # Cria documento
            doc_id = self._generate_document_id(source_id, f"{content.url}:html")
            
            document = ParsedDocument(
                document_id=doc_id,
                source_id=source_id,
                title=title or f"HTML Document - {content.url}",
                content=cleaned_content,
                content_preview=self._create_preview(cleaned_content),
                content_type="text/html",
                content_hash=self._generate_content_hash(cleaned_content),
                url=content.url,
                metadata={
                    "original_encoding": encoding,
                    "css_selector_used": css_selector,
                    "title_selector_used": title_selector,
                    "sanitized": sanitize,
                    "entity_count": entity_count,
                },
                parsed_at=datetime.utcnow(),
                parsing_duration_ms=0,
            )
            
            documents.append(document)
            
            # Calcula tamanho total parseado
            parsed_size = len(cleaned_content)
            
            # Calcula duração
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            metrics.record_success("html")
            
            return ParseResult(
                documents=documents,
                errors=errors,
                raw_content_size=raw_size,
                parsed_content_size=parsed_size,
                duration_seconds=duration,
            )
            
        except UnicodeDecodeError as e:
            raw_size = len(content.get_content()) if content.content_path or content.content else 0
            error_details = {
                "error": f"Encoding error: {str(e)}",
                "error_type": "UnicodeDecodeError",
                "encoding": encoding,
            }
            metrics.record_error("UnicodeDecodeError", "html")
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
            
        except Exception as e:
            raw_size = len(content.get_content()) if content.content_path or content.content else 0
            error_details = {
                "error": f"Unexpected error: {str(e)}",
                "error_type": type(e).__name__,
            }
            quarantine_path = _quarantine_file(content, type(e).__name__, error_details)
            metrics.record_error(type(e).__name__, "html", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )


# Registra parsers built-in
register_parser("csv", CSVParser())
register_parser("html", HTMLParser())


# =============================================================================
# PDF Parser
# =============================================================================

class PDFParser(BaseParser):
    """Parser para arquivos PDF.
    
    Usa pdfplumber para extrair texto mantendo a estrutura do documento.
    Suporta extração de metadados e divisão por páginas.
    
    Security Features:
        - Page limits (default 1000, max 10000)
        - Password-protected PDF handling
        - OCR fallback for image-based PDFs (optional)
        - Size limits per page
        - Quarantine for suspicious files
    """
    
    DEFAULT_EXTRACT_PAGES = False
    
    def _is_password_protected(self, raw_content: bytes) -> bool:
        """Verifica se o PDF está protegido por senha.
        
        Args:
            raw_content: Conteúdo PDF em bytes
            
        Returns:
            True se o PDF está protegido por senha
        """
        try:
            # Check for encryption in PDF header
            # PDFs encrypted with passwords have /Encrypt in the trailer
            header = raw_content[:1024].decode('latin-1', errors='ignore')
            if '/Encrypt' in header:
                return True
            
            # Also check with pdfplumber
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw_content)) as pdf:
                # Try to access first page - will fail if password protected
                if pdf.pages:
                    _ = pdf.pages[0].extract_text()
            return False
        except Exception as e:
            error_str = str(e).lower()
            if any(kw in error_str for kw in ['password', 'encrypted', 'crypt']):
                return True
            return False
    
    def _try_ocr_extraction(self, raw_content: bytes, page_limit: int = 10) -> Tuple[str, List[Dict[str, Any]]]:
        """Tenta extrair texto usando OCR para PDFs baseados em imagem.
        
        Args:
            raw_content: Conteúdo PDF em bytes
            page_limit: Máximo de páginas para OCR
            
        Returns:
            Tuple (extracted_text, ocr_errors)
        """
        ocr_errors = []
        
        try:
            # Try to import pytesseract and pdf2image
            import pytesseract
            from pdf2image import convert_from_bytes
            from PIL import Image
            
            # Convert PDF to images (limited pages)
            images = convert_from_bytes(
                raw_content, 
                first_page=1, 
                last_page=page_limit,
                dpi=150  # Lower DPI for faster processing
            )
            
            text_parts = []
            for i, image in enumerate(images):
                try:
                    # Extract text from image
                    page_text = pytesseract.image_to_string(image, lang='por+eng')
                    if page_text.strip():
                        text_parts.append(f"--- Page {i+1} ---\n{page_text}")
                except Exception as e:
                    ocr_errors.append({
                        "page": i + 1,
                        "error": f"OCR failed: {str(e)}",
                        "error_type": "OCRError",
                    })
            
            return "\n\n".join(text_parts), ocr_errors
            
        except ImportError as e:
            # OCR libraries not available
            ocr_errors.append({
                "error": f"OCR not available: {str(e)}. Install pytesseract, pdf2image, and pillow.",
                "error_type": "OCRNotAvailable",
            })
            return "", ocr_errors
        except Exception as e:
            ocr_errors.append({
                "error": f"OCR extraction failed: {str(e)}",
                "error_type": "OCRFailed",
            })
            return "", ocr_errors
    
    async def parse(self, content: FetchedContent, config: dict) -> ParseResult:
        """Parseia conteúdo PDF em documentos.
        
        Extrai texto do PDF mantendo a estrutura do documento.
        Pode extrair como documento único ou dividir por páginas.
        
        Security:
            - Respects page limits (default: 1000, max: 10000)
            - Handles password-protected PDFs gracefully
            - OCR fallback for image-based PDFs
            - Size limits per page
            - Quarantine for suspicious files
        
        Args:
            content: Conteúdo PDF buscado (bytes)
            config: Configuração com:
                - extract_pages: Se True, cria um documento por página
                - source_id: ID da fonte (obrigatório)
                - max_pages: Máximo de páginas a processar (padrão: 1000)
                - ocr_fallback: Se True, tenta OCR para PDFs sem texto (padrão: False)
                - ocr_page_limit: Máximo de páginas para OCR (padrão: 10)
                - password: Senha para PDFs protegidos (opcional)
                
        Returns:
            ParseResult com documentos extraídos
        """
        import pdfplumber
        
        start_time = datetime.utcnow()
        documents: List[ParsedDocument] = []
        errors: List[Dict[str, Any]] = []
        metrics = get_parse_error_metrics()
        
        # Configurações
        extract_pages = config.get("extract_pages", self.DEFAULT_EXTRACT_PAGES)
        source_id = config.get("source_id", "unknown")
        max_pages = min(config.get("max_pages", DEFAULT_PDF_MAX_PAGES), PDF_MAX_PAGES_HARD)
        ocr_fallback = config.get("ocr_fallback", False)
        ocr_page_limit = config.get("ocr_page_limit", 10)
        password = config.get("password")
        
        # Get content (handles both streamed and in-memory)
        raw_content = content.get_content()
        raw_size = len(raw_content)
        
        # Check size limit
        within_limit, _ = self._check_size_limit(content, MAX_PARSE_SIZE)
        if not within_limit:
            error_type = "SizeLimitExceeded"
            error_details = {
                "error": f"PDF size ({raw_size} bytes) exceeds maximum ({MAX_PARSE_SIZE} bytes)",
                "error_type": error_type,
                "size_bytes": raw_size,
                "max_size_bytes": MAX_PARSE_SIZE,
            }
            quarantine_path = _quarantine_file(content, error_type, error_details)
            metrics.record_error(error_type, "pdf", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
        
        # Check for password-protected PDF
        if self._is_password_protected(raw_content):
            error_type = "PDFPasswordProtected"
            error_details = {
                "error": "PDF is password-protected. Provide password in config or request manual review.",
                "error_type": error_type,
                "hint": "Add 'password' to parser config or contact document owner.",
            }
            quarantine_path = _quarantine_file(content, error_type, error_details)
            metrics.record_error(error_type, "pdf", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )
        
        try:
            # Abre o PDF a partir dos bytes
            with pdfplumber.open(io.BytesIO(raw_content)) as pdf:
                # Extrai metadados do PDF
                pdf_metadata = pdf.metadata or {}
                pdf_title = pdf_metadata.get("Title") or pdf_metadata.get("title")
                total_pages = len(pdf.pages)
                
                # Check page limit
                if total_pages > max_pages:
                    errors.append({
                        "error": f"PDF has {total_pages} pages, exceeding limit of {max_pages}. Processing only first {max_pages} pages.",
                        "error_type": "PageLimitExceeded",
                        "total_pages": total_pages,
                        "max_pages": max_pages,
                        "pages_processed": max_pages,
                    })
                    pages_to_process = max_pages
                else:
                    pages_to_process = total_pages
                
                text_extracted = False
                
                if extract_pages:
                    # Cria um documento por página
                    for page_num in range(1, pages_to_process + 1):
                        try:
                            page = pdf.pages[page_num - 1]
                            page_text = page.extract_text() or ""
                            page_text = page_text.strip()
                            
                            # Skip empty pages
                            if not page_text:
                                continue
                            
                            # Check page text size
                            if len(page_text) > MAX_PDF_TEXT_SIZE_PER_PAGE:
                                errors.append({
                                    "page": page_num,
                                    "error": f"Page text size ({len(page_text)} bytes) exceeds limit ({MAX_PDF_TEXT_SIZE_PER_PAGE} bytes)",
                                    "error_type": "PageTextSizeExceeded",
                                })
                                continue
                            
                            text_extracted = True
                            
                            # Gera ID único para a página
                            doc_id = self._generate_document_id(
                                source_id,
                                f"{content.url}:page_{page_num}"
                            )
                            
                            # Título da página
                            page_title = f"{pdf_title or 'PDF'} - Page {page_num}" if pdf_title else f"Page {page_num}"
                            
                            document = ParsedDocument(
                                document_id=doc_id,
                                source_id=source_id,
                                title=page_title,
                                content=page_text,
                                content_preview=self._create_preview(page_text),
                                content_type="application/pdf",
                                content_hash=self._generate_content_hash(page_text),
                                url=content.url,
                                metadata={
                                    "page_number": page_num,
                                    "total_pages": total_pages,
                                    "pdf_title": pdf_title,
                                    "pdf_metadata": pdf_metadata,
                                    "page_limit_applied": pages_to_process < total_pages,
                                },
                                parsed_at=datetime.utcnow(),
                                parsing_duration_ms=0,
                            )
                            
                            documents.append(document)
                            
                        except Exception as e:
                            errors.append({
                                "page": page_num,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            })
                else:
                    # Extrai texto de todas as páginas como um único documento
                    all_text_parts = []
                    for page_num in range(1, pages_to_process + 1):
                        try:
                            page = pdf.pages[page_num - 1]
                            page_text = page.extract_text() or ""
                            page_text = page_text.strip()
                            
                            # Check page text size
                            if len(page_text) > MAX_PDF_TEXT_SIZE_PER_PAGE:
                                errors.append({
                                    "page": page_num,
                                    "error": f"Page text size ({len(page_text)} bytes) exceeds limit ({MAX_PDF_TEXT_SIZE_PER_PAGE} bytes)",
                                    "error_type": "PageTextSizeExceeded",
                                })
                                continue
                            
                            if page_text:
                                text_extracted = True
                                all_text_parts.append(page_text)
                        except Exception as e:
                            errors.append({
                                "page": page_num,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            })
                    
                    full_text = "\n\n".join(all_text_parts)
                    
                    if full_text.strip():
                        doc_id = self._generate_document_id(source_id, content.url)
                        
                        document = ParsedDocument(
                            document_id=doc_id,
                            source_id=source_id,
                            title=pdf_title or "PDF Document",
                            content=full_text,
                            content_preview=self._create_preview(full_text),
                            content_type="application/pdf",
                            content_hash=self._generate_content_hash(full_text),
                            url=content.url,
                            metadata={
                                "total_pages": total_pages,
                                "pdf_title": pdf_title,
                                "pdf_metadata": pdf_metadata,
                                "extract_pages": False,
                                "page_limit_applied": pages_to_process < total_pages,
                            },
                            parsed_at=datetime.utcnow(),
                            parsing_duration_ms=0,
                        )
                        
                        documents.append(document)
                
                # Try OCR fallback if no text was extracted and OCR is enabled
                if not text_extracted and ocr_fallback:
                    logger.info(f"No text extracted from PDF, trying OCR: {content.url}")
                    ocr_text, ocr_errors = self._try_ocr_extraction(raw_content, ocr_page_limit)
                    errors.extend(ocr_errors)
                    
                    if ocr_text.strip():
                        doc_id = self._generate_document_id(source_id, f"{content.url}:ocr")
                        
                        document = ParsedDocument(
                            document_id=doc_id,
                            source_id=source_id,
                            title=f"{pdf_title or 'PDF Document'} (OCR)",
                            content=ocr_text,
                            content_preview=self._create_preview(ocr_text),
                            content_type="application/pdf",
                            content_hash=self._generate_content_hash(ocr_text),
                            url=content.url,
                            metadata={
                                "total_pages": total_pages,
                                "pdf_title": pdf_title,
                                "ocr_extracted": True,
                                "ocr_page_limit": ocr_page_limit,
                            },
                            parsed_at=datetime.utcnow(),
                            parsing_duration_ms=0,
                        )
                        
                        documents.append(document)
            
            # Calcula tamanho total parseado
            parsed_size = sum(len(doc.content) for doc in documents)
            
            # Calcula duração
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            metrics.record_success("pdf")
            
            return ParseResult(
                documents=documents,
                errors=errors,
                raw_content_size=raw_size,
                parsed_content_size=parsed_size,
                duration_seconds=duration,
            )
            
        except Exception as e:
            error_type = type(e).__name__
            error_details = {
                "error": f"PDF parse error: {str(e)}",
                "error_type": error_type,
            }
            quarantine_path = _quarantine_file(content, error_type, error_details)
            metrics.record_error(error_type, "pdf", bool(quarantine_path))
            
            return ParseResult(
                documents=[],
                errors=[error_details],
                raw_content_size=raw_size,
                parsed_content_size=0,
                duration_seconds=0.0,
            )


# Registra parsers built-in
register_parser("pdf", PDFParser())


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Base classes
    "BaseParser",
    "ContentParser",
    "ParserRegistry",
    # Security constants
    "MAX_PARSE_SIZE",
    "MAX_CSV_ROWS",
    "MAX_HTML_ENTITY_EXPANSION",
    "MAX_HTML_SIZE",
    "DEFAULT_PDF_MAX_PAGES",
    "PDF_MAX_PAGES_HARD",
    # Parsers
    "CSVParser",
    "HTMLParser",
    "PDFParser",
    # Registry functions
    "get_registry",
    "register_parser",
    "get_parser",
    # Security utilities
    "ParseErrorMetrics",
    "get_parse_error_metrics",
    "_quarantine_file",
    "_check_html_entity_expansion",
    "_sanitize_html_content",
    "_detect_csv_dialect",
]
