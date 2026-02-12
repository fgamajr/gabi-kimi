"""Router FastAPI para busca híbrida (BM25 + Vetorial).

Este módulo fornece endpoints para busca híbrida combinando BM25 no Elasticsearch
com busca vetorial semântica, usando RRF (Reciprocal Rank Fusion) para fusão.

Baseado em GABI_SPECS_FINAL_v1.md Seção 4.1 (Search API).

NOTA: A implementação do SearchService foi consolidada em
`gabi.services.search_service`. Este módulo contém apenas
os handlers HTTP que utilizam o serviço centralizado.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from gabi.middleware.rate_limit import RateLimitMiddleware

from gabi.config import Settings, settings
from gabi.auth.middleware import RequireAuth
from gabi.dependencies import get_es_client, get_settings
from gabi.schemas.search import (
    HealthResponse,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)
from gabi.pipeline.embedder import Embedder
from gabi.services.search_service import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


# =============================================================================
# Security: Input Sanitization and Validation
# =============================================================================

# Allowed filter fields for validation
ALLOWED_FILTER_FIELDS = {
    "status", "type", "date_from", "date_to", "tags"
}


# Maximum query complexity limits
MAX_QUERY_LENGTH = 500
MAX_QUERY_DEPTH = 3  # Nested parentheses depth
MAX_FILTER_VALUES = 50  # Max values in filters like tags


def _sanitize_search_query(query: str) -> str:
    """Sanitize search query to prevent ES injection.
    
    Args:
        query: Raw search query from user input
        
    Returns:
        Sanitized query safe for Elasticsearch
    """
    # Remove ES special characters that could alter query structure
    sanitized = re.sub(r'[\{\}\[\]\\"]', '', query)
    # Limit length
    return sanitized[:1000]  # Max 1000 chars


def _validate_filters(filters: Optional[Dict[str, Any]]) -> None:
    """Validate filter fields against allowed list and sanitize values.
    
    Args:
        filters: Dictionary of filter fields
        
    Raises:
        HTTPException: If any filter field is not in the allowed list
                     or if filter values are invalid
    """
    if filters is None:
        return
    
    for field, value in filters.items():
        if field not in ALLOWED_FILTER_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filter field: {field}. Allowed: {ALLOWED_FILTER_FIELDS}"
            )
        
        # Validate and sanitize filter values
        if field == "tags":
            if not isinstance(value, list):
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter '{field}' must be a list"
                )
            if len(value) > MAX_FILTER_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter '{field}' exceeds max {MAX_FILTER_VALUES} values"
                )
            # Sanitize tag values (remove ES special chars)
            filters[field] = [
                re.sub(r'[\{\}\[\]\\"]', '', str(tag))[:100]
                for tag in value
            ]
        elif field in ("status", "type"):
            # Sanitize string values
            if not isinstance(value, str):
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter '{field}' must be a string"
                )
            filters[field] = re.sub(r'[\{\}\[\]\\"]', '', value)[:100]
        elif field in ("date_from", "date_to"):
            # Validate date format (ISO 8601)
            if value and not isinstance(value, str):
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter '{field}' must be a date string (ISO 8601)"
                )


def _validate_query_complexity(query: str) -> None:
    """Validate query complexity to prevent abuse.
    
    Args:
        query: Search query string
        
    Raises:
        HTTPException: If query exceeds complexity limits
    """
    # Check query length
    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Query exceeds maximum length of {MAX_QUERY_LENGTH} characters"
        )
    
    # Check nesting depth (parentheses)
    depth = 0
    max_depth = 0
    for char in query:
        if char == '(':
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ')':
            depth -= 1
        if max_depth > MAX_QUERY_DEPTH:
            raise HTTPException(
                status_code=400,
                detail=f"Query nesting exceeds maximum depth of {MAX_QUERY_DEPTH}"
            )


# =============================================================================
# Dependency Injection
# =============================================================================

async def get_search_service(
    es_client: Any = Depends(get_es_client),
    app_settings: Settings = Depends(get_settings),
) -> AsyncGenerator[SearchService, None]:
    """Dependency injection para SearchService.
    
    Args:
        es_client: Cliente Elasticsearch (injetado)
        app_settings: Configurações (injetadas)
        
    Yields:
        SearchService configurado
    """
    embedder = None
    embeddings_url = getattr(app_settings, "embeddings_url", None)
    if isinstance(embeddings_url, str) and embeddings_url:
        embedder = Embedder(
            base_url=embeddings_url,
            model=getattr(app_settings, "embeddings_model", settings.embeddings_model),
            batch_size=getattr(app_settings, "embeddings_batch_size", settings.embeddings_batch_size),
            timeout=getattr(app_settings, "embeddings_timeout", settings.embeddings_timeout),
            max_retries=getattr(app_settings, "embeddings_max_retries", settings.embeddings_max_retries),
        )
    service = SearchService(
        es_client=es_client,
        embedding_service=embedder,
        settings=app_settings,
        vector_search_backend="elasticsearch",
    )
    try:
        yield service
    finally:
        if embedder:
            await embedder.close()


# =============================================================================
# Endpoints
# =============================================================================

@router.post(
    "/",
    response_model=SearchResponse,
    summary="Busca híbrida",
    description="Executa busca híbrida combinando BM25 e vetorial via RRF",
    responses={
        200: {"description": "Busca executada com sucesso"},
        400: {"description": "Parâmetros inválidos"},
        500: {"description": "Erro interno"},
    },
)
async def search(
    request: SearchRequest,
    http_request: Request,
    service: SearchService = Depends(get_search_service),
    user: dict = Depends(RequireAuth()),
) -> SearchResponse:
    """Endpoint POST /search - busca híbrida.
    
    Executa busca híbrida combinando BM25 no Elasticsearch com
    busca vetorial semântica via ES kNN, usando RRF para fusão de resultados.
    
    Rate Limit: 30 requests per minute for search (stricter than general limit).
    
    Args:
        request: Parâmetros da busca
        http_request: HTTP request object for rate limiting
        service: Serviço de busca (injetado)
        user: Usuário autenticado
        
    Returns:
        SearchResponse com resultados ranqueados
        
    Raises:
        HTTPException: Em caso de erro na busca ou rate limit exceeded
    """
    try:
        # Apply rate limiting for search (stricter limits)
        rate_limit_key = _get_search_rate_limit_key(http_request, user)
        is_allowed, remaining, retry_after = await _check_search_rate_limit(rate_limit_key)
        
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Search rate limit exceeded. Try again in {retry_after} seconds.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": "30",
                    "X-RateLimit-Remaining": "0",
                }
            )
        
        # Validate query complexity
        _validate_query_complexity(request.query)
        
        # Validate filter fields and sanitize values
        _validate_filters(request.filters)
        
        # Sanitize the query
        safe_query = _sanitize_search_query(request.query)
        
        # Create sanitized request
        sanitized_request = SearchRequest(
            query=safe_query,
            sources=request.sources,
            filters=request.filters,
            limit=request.limit,
            offset=request.offset,
            hybrid_weights=request.hybrid_weights,
        )
        
        response = await service.search_api(sanitized_request)
        
        # Add rate limit headers to response
        response_headers = {
            "X-RateLimit-Limit": "30",
            "X-RateLimit-Remaining": str(remaining),
        }
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro na busca: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao executar busca: {str(e)}",
        )


# Search-specific rate limiting
SEARCH_RATE_LIMIT_REQUESTS = 30  # requests per minute for search
SEARCH_RATE_LIMIT_WINDOW = 60  # seconds


def _get_search_rate_limit_key(request: Request, user: dict) -> str:
    """Generate rate limit key for search endpoint.
    
    Args:
        request: FastAPI request object
        user: Authenticated user dict
        
    Returns:
        Rate limit key string
    """
    # Use user ID if available, otherwise IP
    user_id = user.get("sub")
    if user_id:
        return f"gabi:search:ratelimit:user:{user_id}"
    
    client_host = request.client.host if request.client else "unknown"
    return f"gabi:search:ratelimit:ip:{client_host}"


async def _check_search_rate_limit(key: str) -> tuple[bool, int, int]:
    """Check search-specific rate limit.
    
    Args:
        key: Rate limit key
        
    Returns:
        Tuple of (is_allowed, remaining_requests, retry_after_seconds)
    """
    try:
        from gabi.db import get_redis_client
        redis_client = get_redis_client()
        
        if not redis_client:
            # Redis unavailable - allow request
            return True, SEARCH_RATE_LIMIT_REQUESTS, 0
        
        # Increment counter
        current_count = await redis_client.incr(key)
        
        # Set expiry on first request
        if current_count == 1:
            await redis_client.expire(key, SEARCH_RATE_LIMIT_WINDOW)
        
        # Check limit
        is_allowed = current_count <= SEARCH_RATE_LIMIT_REQUESTS
        remaining = max(0, SEARCH_RATE_LIMIT_REQUESTS - int(current_count))
        retry_after = SEARCH_RATE_LIMIT_WINDOW if not is_allowed else 0
        
        return is_allowed, remaining, retry_after
        
    except Exception as e:
        logger.warning(f"Rate limit check failed: {e}")
        # Fail open - allow request
        return True, SEARCH_RATE_LIMIT_REQUESTS, 0


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check dos índices",
    description="Retorna status de saúde dos índices Elasticsearch",
    responses={
        200: {"description": "Health check executado"},
        503: {"description": "Serviço indisponível"},
    },
)
async def health(
    service: SearchService = Depends(get_search_service),
) -> HealthResponse:
    """Endpoint GET /search/health - health check dos índices.
    
    Verifica saúde dos índices Elasticsearch usados para busca,
    incluindo estatísticas de documentos e tamanho.
    
    Args:
        service: Serviço de busca (injetado)
        
    Returns:
        HealthResponse com status dos índices
        
    Raises:
        HTTPException: 503 se serviço indisponível
    """
    try:
        result = await service.health_check()
        
        if result.status == "unhealthy":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Search service unhealthy",
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro no health check: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Search service unavailable: {str(e)}",
        )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Router
    "router",
    # Schemas (re-exported from schemas module)
    "SearchRequest",
    "SearchResponse",
    # Service (re-exported from services module)
    "SearchService",
    "get_search_service",
]
