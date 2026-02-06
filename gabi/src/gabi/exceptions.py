"""
GABI - Exception Hierarchy

Gerador Automático de Boletins por Inteligência Artificial
Sistema de exceções customizadas com suporte a:
- Hierarquia semântica de erros
- Códigos de erro padronizados
- Metadados para retry e observabilidade
- Integração com logging estruturado
"""

from typing import Any, Optional


__all__ = [
    # Base
    "GABIException",
    # Configuração
    "ConfigurationError",
    # Pipeline
    "PipelineError",
    "DiscoveryError",
    "FetcherError",
    "ParserError",
    "DeduplicationError",
    "EmbeddingError",
    "IndexError",
    # Database & Search
    "DatabaseError",
    "SearchError",
    # Auth & Rate Limit
    "AuthError",
    "RateLimitError",
    # Validation
    "ValidationError",
]


class GABIException(Exception):
    """
    Exceção base para todos os erros do GABI.
    
    Attributes:
        message: Mensagem de erro legível
        details: Dicionário com contexto adicional do erro
        retryable: Indica se a operação pode ser tentada novamente
        error_code: Código de erro padronizado (ex: "PIPELINE_FETCH_001")
    """
    
    # Prefixo padrão para códigos de erro desta classe
    ERROR_PREFIX = "GABI"
    # Contador sequencial para códigos de erro
    _error_counter = 0
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = False,
        error_code: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.error_code = error_code or self._generate_error_code()
    
    def _generate_error_code(self) -> str:
        """Gera um código de erro único baseado no prefixo da classe."""
        GABIException._error_counter += 1
        return f"{self.ERROR_PREFIX}_{GABIException._error_counter:03d}"
    
    def __str__(self) -> str:
        parts = [f"[{self.error_code}] {self.message}"]
        if self.details:
            parts.append(f"details={self.details}")
        if self.retryable:
            parts.append("(retryable)")
        return " | ".join(parts)
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"error_code='{self.error_code}', "
            f"message='{self.message}', "
            f"retryable={self.retryable}, "
            f"details={self.details}"
            f")"
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Converte a exceção para dicionário (útil para logging/API responses)."""
        return {
            "error_code": self.error_code,
            "error_type": self.__class__.__name__,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


# =============================================================================
# ERROS DE CONFIGURAÇÃO
# =============================================================================

class ConfigurationError(GABIException):
    """
    Erro na configuração do sistema.
    
    Exemplos:
        - Arquivo de configuração inválido
        - Variável de ambiente obrigatória ausente
        - Valor de configuração fora do range aceitável
    """
    ERROR_PREFIX = "CONFIG"


# =============================================================================
# ERROS DO PIPELINE DE INGESTÃO
# =============================================================================

class PipelineError(GABIException):
    """
    Erro genérico no pipeline de ingestão de documentos.
    
    Base para todos os erros específicos de cada etapa do pipeline.
    """
    ERROR_PREFIX = "PIPELINE"


class DiscoveryError(PipelineError):
    """
    Erro na etapa de discovery (descoberta de documentos).
    
    Exemplos:
        - Fonte indisponível
        - RSS feed inválido
        - Timeout na listagem de documentos
    """
    ERROR_PREFIX = "DISCOVERY"


class FetcherError(PipelineError):
    """
    Erro na etapa de fetch (download de documentos).
    
    Exemplos:
        - HTTP 404/500
        - Timeout de download
        - Arquivo muito grande
        - SSL/TLS error
    """
    ERROR_PREFIX = "FETCH"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Por padrão, erros de fetch são retryable
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


class ParserError(PipelineError):
    """
    Erro na etapa de parsing (extração de conteúdo).
    
    Exemplos:
        - PDF corrompido
        - Formato não suportado
        - Encoding inválido
        - Estrutura de documento inesperada
    """
    ERROR_PREFIX = "PARSE"


class DeduplicationError(PipelineError):
    """
    Erro na etapa de deduplicação.
    
    Exemplos:
        - Falha ao calcular hash
        - Erro no cache de dedup
        - Condição de corrida
    """
    ERROR_PREFIX = "DEDUP"


class EmbeddingError(PipelineError):
    """
    Erro na etapa de geração de embeddings.
    
    Exemplos:
        - Serviço de embeddings indisponível
        - Modelo não carregado
        - Texto muito longo para o modelo
        - Erro de GPU/memória
    """
    ERROR_PREFIX = "EMBED"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Por padrão, erros de embedding são retryable
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


class IndexError(PipelineError):
    """
    Erro na etapa de indexação (armazenamento nos índices).
    
    Exemplos:
        - Falha ao inserir no PostgreSQL
        - Falha ao indexar no Elasticsearch
        - Violacao de constraint
        - Erro de conexão com banco
    """
    ERROR_PREFIX = "INDEX"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Por padrão, erros de indexação são retryable
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


# =============================================================================
# ERROS DE BANCO DE DADOS E BUSCA
# =============================================================================

class DatabaseError(GABIException):
    """
    Erro em operações de banco de dados.
    
    Exemplos:
        - Connection pool esgotado
        - Query timeout
        - Deadlock
        - Constraint violation
    """
    ERROR_PREFIX = "DB"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Por padrão, erros de DB são retryable (exceto violações)
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


class SearchError(GABIException):
    """
    Erro em operações de busca.
    
    Exemplos:
        - Elasticsearch indisponível
        - Query syntax error
        - Timeout na busca
        - Índice não encontrado
    """
    ERROR_PREFIX = "SEARCH"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Por padrão, erros de busca são retryable
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


# =============================================================================
# ERROS DE AUTENTICAÇÃO E AUTORIZAÇÃO
# =============================================================================

class AuthError(GABIException):
    """
    Erro de autenticação ou autorização.
    
    Exemplos:
        - Token JWT inválido
        - Token expirado
        - Permissões insuficientes
        - Falha na verificação de MFA
    """
    ERROR_PREFIX = "AUTH"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = False,  # Auth errors geralmente não são retryable
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)


class RateLimitError(GABIException):
    """
    Erro de rate limiting.
    
    Indica que o limite de requisições foi excedido.
    """
    ERROR_PREFIX = "RATE"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = True,  # Rate limit é sempre retryable (após espera)
        retry_after: Optional[int] = None,  # Segundos para retry
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)
        self.retry_after = retry_after
        if retry_after is not None:
            self.details["retry_after_seconds"] = retry_after


# =============================================================================
# ERROS DE VALIDAÇÃO
# =============================================================================

class ValidationError(GABIException):
    """
    Erro de validação de dados.
    
    Exemplos:
        - Schema inválido
        - Campo obrigatório ausente
        - Tipo de dado incorreto
        - Valor fora do range permitido
    """
    ERROR_PREFIX = "VALIDATION"
    
    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        retryable: bool = False,  # Validation errors raramente são retryable
        field: Optional[str] = None,
        error_code: Optional[str] = None,
    ):
        super().__init__(message, details, retryable, error_code)
        self.field = field
        if field is not None:
            self.details["field"] = field
