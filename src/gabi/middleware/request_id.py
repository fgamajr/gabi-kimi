"""Correlation ID middleware para tracing distribuído."""

import uuid
from contextvars import ContextVar
from typing import Callable, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ContextVar para acessar request_id em qualquer lugar do código
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Gera e propaga correlation IDs para tracing.
    
    Lógica:
    1. Se header X-Correlation-ID presente, usa-o
    2. Se header X-Request-ID presente, usa-o como correlation_id
    3. Gera novo UUID se nenhum header presente
    
    Headers propagados:
    - X-Request-ID: ID único deste request
    - X-Correlation-ID: ID de correlação entre serviços
    """
    
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Processa request adicionando IDs de correlação."""
        # Extrair ou gerar correlation ID
        correlation_id = (
            request.headers.get("X-Correlation-ID")
            or request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )
        
        # Gerar request ID único
        request_id = str(uuid.uuid4())
        
        # Setar nos headers se não existirem
        request.headers.__dict__["_list"].append(
            (b"x-request-id", request_id.encode())
        )
        request.headers.__dict__["_list"].append(
            (b"x-correlation-id", correlation_id.encode())
        )
        
        # Guardar no state e ContextVar
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        
        token_request = request_id_var.set(request_id)
        token_correlation = correlation_id_var.set(correlation_id)
        
        try:
            response = await call_next(request)
            
            # Adicionar headers na resposta
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            
            return response
            
        finally:
            request_id_var.reset(token_request)
            correlation_id_var.reset(token_correlation)


def get_request_id() -> Optional[str]:
    """Obtém request_id atual do contexto.
    
    Returns:
        Request ID ou None se não estiver em contexto de request
    """
    return request_id_var.get()


def get_correlation_id() -> Optional[str]:
    """Obtém correlation_id atual do contexto.
    
    Returns:
        Correlation ID ou None se não estiver em contexto de request
    """
    return correlation_id_var.get()


class RequestIDLogFilter:
    """Filtro para adicionar request_id em logs.
    
    Uso com structlog ou logging padrão:
        logger = logging.getLogger(__name__)
        logger.addFilter(RequestIDLogFilter())
    """
    
    def filter(self, record) -> bool:
        """Adiciona request_id e correlation_id no registro de log."""
        record.request_id = get_request_id() or "N/A"
        record.correlation_id = get_correlation_id() or "N/A"
        return True
