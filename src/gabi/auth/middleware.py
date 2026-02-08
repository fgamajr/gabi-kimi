"""Middleware de autenticação para FastAPI."""

from typing import Callable, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from gabi.auth.jwt import JWTValidator
from gabi.config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware de autenticação JWT.
    
    Valida tokens JWT RS256 emitidos pelo Keycloak TCU.
    Path públicos são configuráveis via public_paths.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        public_paths: Optional[List[str]] = None,
        validator: Optional[JWTValidator] = None,
    ) -> None:
        super().__init__(app)
        self.public_paths = public_paths or []
        self.validator = validator or JWTValidator()
    
    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        """Processa request verificando autenticação."""
        # Verificar se path é público
        path = request.url.path
        if self._is_public_path(path):
            return await call_next(request)
        
        # Extrair token do header Authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorized("Missing or invalid authorization header")
        
        token = auth_header[7:]  # Remover "Bearer "
        if not token:
            return self._unauthorized("Empty token")
        
        # Validar token
        try:
            payload = await self.validator.validate(token)
            request.state.user = payload
            request.state.user_id = payload.get("sub")
            request.state.user_roles = payload.get("realm_access", {}).get("roles", [])
        except JWTError as exc:
            return self._unauthorized(f"Invalid token: {str(exc)}")
        except Exception as exc:
            return self._unauthorized(f"Authentication failed: {str(exc)}")
        
        return await call_next(request)
    
    def _is_public_path(self, path: str) -> bool:
        """Verifica se path está na lista de públicos."""
        for public_path in self.public_paths:
            if path.startswith(public_path):
                return True
        return False
    
    def _unauthorized(self, message: str) -> JSONResponse:
        """Retorna resposta 401."""
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": message,
            },
            headers={"WWW-Authenticate": 'Bearer realm="gabi-api"'},
        )


class RequireAuth:
    """Dependency para exigir autenticação em endpoints.
    
    Uso:
        @app.get("/protected")
        async def protected(user: dict = Depends(RequireAuth())):
            return {"user": user}
    """
    
    def __init__(self, roles: Optional[List[str]] = None) -> None:
        self.roles = roles or []
    
    async def __call__(self, request: Request) -> dict:
        """Verifica autenticação e roles."""
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": 'Bearer realm="gabi-api"'},
            )
        
        if self.roles:
            user_roles = set(user.get("realm_access", {}).get("roles", []))
            if not any(role in user_roles for role in self.roles):
                raise HTTPException(
                    status_code=403,
                    detail="Insufficient permissions",
                )
        
        return user
