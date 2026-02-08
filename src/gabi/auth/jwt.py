"""Validação JWT RS256 com cache JWKS."""

import time
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx
from jose import JWTError, jwt
from jose.backends import RSAKey

from gabi.auth.token_revocation import revocation_list
from gabi.config import settings

# Security: Maximum number of keys to cache to prevent memory exhaustion
MAX_JWKS_KEYS = 20


class JWKSClient:
    """Cliente para buscar e cachear chaves JWKS."""
    
    def __init__(self) -> None:
        self._cache: Dict[str, str] = {}
        self._last_fetch: float = 0
        self._cache_ttl_seconds: int = settings.jwt_jwks_cache_minutes * 60
    
    async def get_key(self, kid: str) -> Optional[str]:
        """Obtém chave PEM pelo Key ID."""
        await self._refresh_if_needed()
        return self._cache.get(kid)
    
    async def _refresh_if_needed(self) -> None:
        """Atualiza cache JWKS se necessário."""
        now = time.time()
        if now - self._last_fetch < self._cache_ttl_seconds and self._cache:
            return
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(str(settings.jwt_jwks_url))
                response.raise_for_status()
                jwks = response.json()
            
            new_cache: Dict[str, str] = {}
            key_count = 0
            for key_data in jwks.get("keys", []):
                if key_count >= MAX_JWKS_KEYS:
                    # Security: Truncate cache to prevent memory exhaustion
                    break
                if key_data.get("kty") == "RSA":
                    kid = key_data.get("kid")
                    if kid:
                        rsa_key = RSAKey(key_data, algorithm=settings.jwt_algorithm)
                        new_cache[kid] = rsa_key.to_pem()
                        key_count += 1
            
            self._cache = new_cache
            self._last_fetch = now
            
        except Exception as exc:
            # Se falhar mas tiver cache, mantém cache atual
            if not self._cache:
                raise JWTError(f"Failed to fetch JWKS: {exc}") from exc
    
    def clear_cache(self) -> None:
        """Limpa cache de chaves."""
        self._cache.clear()
        self._last_fetch = 0


class JWTValidator:
    """Validador de tokens JWT RS256."""
    
    def __init__(self) -> None:
        self._jwks = JWKSClient()
    
    async def validate(self, token: str) -> Dict:
        """Valida token JWT e retorna payload.
        
        Args:
            token: Token JWT string
            
        Returns:
            Payload decodificado do token
            
        Raises:
            JWTError: Se token for inválido
        """
        # Extrair kid do header sem verificar
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError:
            raise JWTError("Invalid token header")
        
        kid = unverified_header.get("kid")
        if not kid:
            raise JWTError("Token missing 'kid' in header")
        
        # Obter chave do cache JWKS
        key_pem = await self._jwks.get_key(kid)
        if not key_pem:
            raise JWTError(f"Unknown key ID: {kid}")
        
        # Decodificar e validar token
        payload = jwt.decode(
            token,
            key_pem,
            algorithms=[settings.jwt_algorithm],
            issuer=str(settings.jwt_issuer),
            audience=settings.jwt_audience,
            options={
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_sub": True,
                "require": ["exp", "iat", "sub", "jti"],
            }
        )
        
        # Verificar se token foi revogado
        jti = payload.get("jti")
        if jti and await revocation_list.is_revoked(jti):
            raise JWTError("Token has been revoked")
        
        # Verificar se todos os tokens do usuário foram revogados
        user_id = payload.get("sub")
        iat = payload.get("iat")
        if user_id and iat:
            # iat pode ser datetime ou timestamp Unix
            if isinstance(iat, datetime):
                issued_at = iat
            else:
                issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
            if await revocation_list.is_user_revoked(user_id, issued_at):
                raise JWTError("User tokens have been revoked")
        
        return payload
    
    def decode_unsafe(self, token: str) -> Optional[Dict]:
        """Decodifica token sem validação (apenas para debug).
        
        Args:
            token: Token JWT string
            
        Returns:
            Payload decodificado ou None se inválido
        """
        try:
            return jwt.get_unverified_claims(token)
        except JWTError:
            return None
