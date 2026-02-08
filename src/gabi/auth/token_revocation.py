"""Token Revocation - Sistema de revogação de tokens JWT.

Este módulo implementa um mecanismo de revogação de tokens usando Redis,
permitindo invalidar tokens antes de sua expiração natural em caso de:
- Comprometimento de credenciais
- Logout explícito do usuário
- Revogação por administrador

Baseado em GABI_SPECS_FINAL_v1.md Seção 5.2 (Security).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from gabi.db import get_redis_client
from gabi.exceptions import AuthenticationError
from gabi.config import settings

logger = logging.getLogger(__name__)


class TokenRevocationList:
    """Lista de revogação de tokens (RL) implementada em Redis.
    
    Usa Redis para armazenar tokens revogados com TTL automático
    baseado na expiração do token.
    
    Attributes:
        redis: Cliente Redis para armazenamento
        key_prefix: Prefixo para chaves no Redis
    """
    
    def __init__(self, key_prefix: str = "gabi:revoked_token") -> None:
        """Inicializa a lista de revogação.
        
        Args:
            key_prefix: Prefixo para chaves no Redis
        """
        self._redis = None
        self.key_prefix = key_prefix
    
    async def _get_redis(self):
        """Obtém cliente Redis (lazy initialization)."""
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis
    
    async def revoke_token(
        self,
        jti: str,
        expires_at: datetime,
        reason: Optional[str] = None,
        revoked_by: Optional[str] = None,
    ) -> bool:
        """Revoga um token pelo seu JTI (JWT ID).
        
        Args:
            jti: JWT ID único do token
            expires_at: Data/hora de expiração do token
            reason: Motivo da revogação (opcional)
            revoked_by: Quem revogou o token (opcional)
            
        Returns:
            True se revogado com sucesso
        """
        try:
            redis = await self._get_redis()
            key = f"{self.key_prefix}:{jti}"
            
            # Calcular TTL baseado na expiração do token
            now = datetime.now(timezone.utc)
            ttl_seconds = int((expires_at - now).total_seconds())
            
            if ttl_seconds <= 0:
                # Token já expirado, não precisa revogar
                logger.debug(f"Token {jti[:8]}... already expired, skipping revocation")
                return True
            
            # Armazenar com TTL automático
            value = {
                "revoked_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "reason": reason or "unknown",
                "revoked_by": revoked_by or "system",
            }
            
            await redis.setex(key, ttl_seconds, json.dumps(value))
            
            logger.info(
                f"Token revoked: {jti[:8]}... (reason: {reason}, by: {revoked_by})"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke token {jti[:8]}...: {e}")
            return False
    
    async def is_revoked(self, jti: str) -> bool:
        """Verifica se um token foi revogado.
        
        Args:
            jti: JWT ID único do token
            
        Returns:
            True se o token foi revogado
        """
        try:
            redis = await self._get_redis()
            key = f"{self.key_prefix}:{jti}"
            
            exists = await redis.exists(key)
            return bool(exists)
            
        except Exception as e:
            logger.error(f"Failed to check revocation for token {jti[:8]}...: {e}")
            # Security: Fail-closed by default in production to prevent revoked tokens
            # from being accepted during Redis outages
            if settings.auth_fail_closed or settings.environment.value == "production":
                raise AuthenticationError(
                    "Cannot verify token revocation status"
                ) from e
            # Only fail-open in development environments
            return False
    
    async def revoke_all_user_tokens(
        self,
        user_id: str,
        reason: str = "user_logout_all",
        revoked_by: Optional[str] = None,
    ) -> bool:
        """Marca todos os tokens de um usuário como revogados.
        
        Nota: Como não armazenamos todos os tokens ativos de um usuário,
        esta função adiciona uma entrada especial que o validator deve verificar.
        
        Args:
            user_id: ID do usuário
            reason: Motivo da revogação
            revoked_by: Quem revogou
            
        Returns:
            True se a operação foi bem-sucedida
        """
        try:
            redis = await self._get_redis()
            key = f"{self.key_prefix}:user:{user_id}:revoked_all"
            
            value = {
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "revoked_by": revoked_by or "system",
            }
            
            # TTL de 24 horas para esta marcação
            await redis.setex(key, 86400, json.dumps(value))
            
            logger.info(f"All tokens revoked for user {user_id} (reason: {reason})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke all tokens for user {user_id}: {e}")
            return False
    
    async def is_user_revoked(self, user_id: str, token_issued_at: datetime) -> bool:
        """Verifica se todos os tokens do usuário foram revogados após uma data.
        
        Args:
            user_id: ID do usuário
            token_issued_at: Quando o token foi emitido
            
        Returns:
            True se os tokens do usuário foram revogados após a emissão
        """
        try:
            redis = await self._get_redis()
            key = f"{self.key_prefix}:user:{user_id}:revoked_all"
            
            value = await redis.get(key)
            if not value:
                return False
            
            # Parse revoked_at
            data = json.loads(value)
            revoked_at = datetime.fromisoformat(data["revoked_at"])
            
            # Token é inválido se foi emitido antes da revogação
            return token_issued_at < revoked_at
            
        except Exception as e:
            logger.error(f"Failed to check user revocation for {user_id}: {e}")
            return False


# Instância global
revocation_list = TokenRevocationList()


async def revoke_token(
    jti: str,
    expires_at: datetime,
    reason: Optional[str] = None,
    revoked_by: Optional[str] = None,
) -> bool:
    """Função utilitária para revogar um token.
    
    Args:
        jti: JWT ID único do token
        expires_at: Data/hora de expiração do token
        reason: Motivo da revogação
        revoked_by: Quem revogou
        
    Returns:
        True se revogado com sucesso
    """
    return await revocation_list.revoke_token(jti, expires_at, reason, revoked_by)


async def is_token_revoked(jti: str) -> bool:
    """Função utilitária para verificar se um token foi revogado.
    
    Args:
        jti: JWT ID do token
        
    Returns:
        True se revogado
    """
    return await revocation_list.is_revoked(jti)
