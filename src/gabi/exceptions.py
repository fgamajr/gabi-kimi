"""Hierarquia de exceções do GABI.

Define exceções específicas para cada componente do sistema,
facilitando o tratamento de erros e logging.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


# =============================================================================
# Exceção Base
# =============================================================================

class GABIException(Exception):
    """Exceção base para todos os erros do GABI.
    
    Attributes:
        message: Mensagem de erro descritiva
        code: Código único do erro para identificação
        details: Detalhes adicionais do erro
        timestamp: Momento em que o erro ocorreu
    """
    
    code: str = "GABI_ERROR"
    status_code: int = 500
    
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte a exceção para dicionário."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "timestamp": self.timestamp.isoformat(),
            }
        }


# =============================================================================
# Exceções de Configuração
# =============================================================================

class ConfigurationError(GABIException):
    """Erro na configuração do sistema."""
    code = "CONFIG_ERROR"
    status_code = 500


class ValidationError(GABIException):
    """Erro de validação de dados."""
    code = "VALIDATION_ERROR"
    status_code = 400


class MissingConfigurationError(ConfigurationError):
    """Configuração obrigatória ausente."""
    code = "MISSING_CONFIG"


class InvalidConfigurationError(ConfigurationError):
    """Configuração com valor inválido."""
    code = "INVALID_CONFIG"


# =============================================================================
# Exceções de Fontes (Sources)
# =============================================================================

class SourceError(GABIException):
    """Erro relacionado a fontes de dados."""
    code = "SOURCE_ERROR"
    status_code = 400


class SourceNotFoundError(SourceError):
    """Fonte não encontrada."""
    code = "SOURCE_NOT_FOUND"
    status_code = 404


class SourceDisabledError(SourceError):
    """Fonte está desabilitada."""
    code = "SOURCE_DISABLED"
    status_code = 409


class SourceConfigError(SourceError):
    """Erro na configuração da fonte."""
    code = "SOURCE_CONFIG_ERROR"
    status_code = 400


class SourceSyncError(SourceError):
    """Erro durante sincronização da fonte."""
    code = "SOURCE_SYNC_ERROR"
    status_code = 500


# =============================================================================
# Exceções de Pipeline
# =============================================================================

class PipelineError(GABIException):
    """Erro no pipeline de ingestão."""
    code = "PIPELINE_ERROR"
    status_code = 500


class DiscoveryError(PipelineError):
    """Erro na fase de discovery."""
    code = "DISCOVERY_ERROR"


class FetchError(PipelineError):
    """Erro ao buscar conteúdo."""
    code = "FETCH_ERROR"


class ParseError(PipelineError):
    """Erro ao fazer parsing do conteúdo."""
    code = "PARSE_ERROR"


class ChunkingError(PipelineError):
    """Erro ao dividir conteúdo em chunks."""
    code = "CHUNKING_ERROR"


class EmbeddingError(PipelineError):
    """Erro ao gerar embeddings."""
    code = "EMBEDDING_ERROR"


class IndexingError(PipelineError):
    """Erro ao indexar documento."""
    code = "INDEXING_ERROR"


class DeduplicationError(PipelineError):
    """Erro na deduplicação."""
    code = "DEDUPLICATION_ERROR"


class CheckpointError(PipelineError):
    """Erro ao salvar ou recuperar checkpoint."""
    code = "CHECKPOINT_ERROR"


# =============================================================================
# Exceções de Documentos
# =============================================================================

class DocumentError(GABIException):
    """Erro relacionado a documentos."""
    code = "DOCUMENT_ERROR"
    status_code = 400


class DocumentNotFoundError(DocumentError):
    """Documento não encontrado."""
    code = "DOCUMENT_NOT_FOUND"
    status_code = 404


class DocumentAlreadyExistsError(DocumentError):
    """Documento já existe."""
    code = "DOCUMENT_EXISTS"
    status_code = 409


class DocumentTooLargeError(DocumentError):
    """Documento excede tamanho máximo permitido."""
    code = "DOCUMENT_TOO_LARGE"
    status_code = 413


class DocumentValidationError(DocumentError):
    """Documento não passou na validação."""
    code = "DOCUMENT_VALIDATION_ERROR"
    status_code = 400


# =============================================================================
# Exceções de Banco de Dados
# =============================================================================

class DatabaseError(GABIException):
    """Erro de banco de dados."""
    code = "DATABASE_ERROR"
    status_code = 500


class ConnectionError(DatabaseError):
    """Erro de conexão com banco de dados."""
    code = "DB_CONNECTION_ERROR"


class TransactionError(DatabaseError):
    """Erro em transação."""
    code = "TRANSACTION_ERROR"


class MigrationError(DatabaseError):
    """Erro em migração."""
    code = "MIGRATION_ERROR"


# =============================================================================
# Exceções de Elasticsearch
# =============================================================================

class ElasticsearchError(GABIException):
    """Erro no Elasticsearch."""
    code = "ELASTICSEARCH_ERROR"
    status_code = 500


class IndexNotFoundError(ElasticsearchError):
    """Índice não encontrado."""
    code = "INDEX_NOT_FOUND"
    status_code = 404


class MappingError(ElasticsearchError):
    """Erro no mapping do índice."""
    code = "MAPPING_ERROR"


class QueryError(ElasticsearchError):
    """Erro na query Elasticsearch."""
    code = "ES_QUERY_ERROR"
    status_code = 400


# =============================================================================
# Exceções de Busca
# =============================================================================

class SearchError(GABIException):
    """Erro durante busca."""
    code = "SEARCH_ERROR"
    status_code = 500


class InvalidSearchQueryError(SearchError):
    """Query de busca inválida."""
    code = "INVALID_SEARCH_QUERY"
    status_code = 400


class SearchTimeoutError(SearchError):
    """Timeout na busca."""
    code = "SEARCH_TIMEOUT"
    status_code = 504


# =============================================================================
# Exceções de Embeddings/TEI
# =============================================================================

class TEIError(GABIException):
    """Erro no serviço TEI de embeddings."""
    code = "TEI_ERROR"
    status_code = 502


class TEITimeoutError(TEIError):
    """Timeout no serviço TEI."""
    code = "TEI_TIMEOUT"
    status_code = 504


class TEIUnavailableError(TEIError):
    """Serviço TEI indisponível."""
    code = "TEI_UNAVAILABLE"
    status_code = 503


class ModelError(GABIException):
    """Erro no modelo de embeddings."""
    code = "MODEL_ERROR"
    status_code = 500


class DimensionMismatchError(ModelError):
    """Dimensionalidade do embedding não corresponde."""
    code = "DIMENSION_MISMATCH"
    status_code = 500


# =============================================================================
# Exceções de Autenticação e Autorização
# =============================================================================

class AuthError(GABIException):
    """Erro de autenticação/autorização."""
    code = "AUTH_ERROR"
    status_code = 401


class AuthenticationError(AuthError):
    """Falha na autenticação."""
    code = "AUTHENTICATION_ERROR"
    status_code = 401


class AuthorizationError(AuthError):
    """Falta permissão para acessar recurso."""
    code = "AUTHORIZATION_ERROR"
    status_code = 403


class TokenExpiredError(AuthenticationError):
    """Token JWT expirado."""
    code = "TOKEN_EXPIRED"


class InvalidTokenError(AuthenticationError):
    """Token JWT inválido."""
    code = "INVALID_TOKEN"


class JWKSFetchError(AuthenticationError):
    """Erro ao buscar chaves JWKS."""
    code = "JWKS_FETCH_ERROR"


# =============================================================================
# Exceções de Rate Limiting
# =============================================================================

class RateLimitError(GABIException):
    """Limite de requisições excedido."""
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


class QuotaExceededError(GABIException):
    """Quota de uso excedida."""
    code = "QUOTA_EXCEEDED"
    status_code = 429


# =============================================================================
# Exceções de DLQ
# =============================================================================

class DLQError(GABIException):
    """Erro na Dead Letter Queue."""
    code = "DLQ_ERROR"
    status_code = 500


class MessageNotFoundError(DLQError):
    """Mensagem não encontrada na DLQ."""
    code = "DLQ_MESSAGE_NOT_FOUND"
    status_code = 404


class RetryExhaustedError(DLQError):
    """Retry attempts esgotados."""
    code = "RETRY_EXHAUSTED"


# =============================================================================
# Exceções de Governança
# =============================================================================

class GovernanceError(GABIException):
    """Erro de governança de dados."""
    code = "GOVERNANCE_ERROR"
    status_code = 400


class AuditError(GovernanceError):
    """Erro no sistema de auditoria."""
    code = "AUDIT_ERROR"


class LineageError(GovernanceError):
    """Erro no lineage de dados."""
    code = "LINEAGE_ERROR"


class QualityCheckError(GovernanceError):
    """Erro na verificação de qualidade."""
    code = "QUALITY_CHECK_ERROR"


class PIIError(GovernanceError):
    """Erro relacionado a dados pessoais (PII)."""
    code = "PII_ERROR"
    status_code = 403


# =============================================================================
# Exceções de Crawler
# =============================================================================

class CrawlerError(GABIException):
    """Erro no crawler web."""
    code = "CRAWLER_ERROR"
    status_code = 500


class RobotsTxtError(CrawlerError):
    """Bloqueado por robots.txt."""
    code = "ROBOTS_TXT_BLOCKED"
    status_code = 403


class CrawlDepthExceededError(CrawlerError):
    """Profundidade máxima de crawl excedida."""
    code = "CRAWL_DEPTH_EXCEEDED"


class PolitenessError(CrawlerError):
    """Erro na política de politeness."""
    code = "POLITENESS_ERROR"


# =============================================================================
# Exceções de Memória e Recursos
# =============================================================================

class ResourceError(GABIException):
    """Erro de recurso do sistema."""
    code = "RESOURCE_ERROR"
    status_code = 503


class MemoryLimitError(ResourceError):
    """Limite de memória excedido."""
    code = "MEMORY_LIMIT_EXCEEDED"
    status_code = 507


class DiskSpaceError(ResourceError):
    """Espaço em disco insuficiente."""
    code = "DISK_SPACE_ERROR"
    status_code = 507


class CircuitBreakerOpenError(ResourceError):
    """Circuit breaker aberto."""
    code = "CIRCUIT_BREAKER_OPEN"
    status_code = 503


# =============================================================================
# Exceções de MCP
# =============================================================================

class MCPError(GABIException):
    """Erro no servidor MCP."""
    code = "MCP_ERROR"
    status_code = 500


class ToolNotFoundError(MCPError):
    """Ferramenta MCP não encontrada."""
    code = "TOOL_NOT_FOUND"
    status_code = 404


class ResourceNotFoundError(MCPError):
    """Recurso MCP não encontrado."""
    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class InvalidToolArgumentsError(MCPError):
    """Argumentos inválidos para ferramenta MCP."""
    code = "INVALID_TOOL_ARGS"
    status_code = 400
